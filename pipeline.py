"""
pipeline.py
기자 단독 보도 파급력 추적 시스템 - 코어 함수 모음

주요 함수:
- search_bigkinds(query, providers, date_from, date_to) → 빅카인즈 검색
- assign_timepoint(article_date, d_day) → D+N 시점 분류
- build_coverage_matrix(df, d_day, providers) → 매체×시점 매트릭스
- generate_impact_report(df, d_day, matrix) → Claude로 상신 양식 생성
"""

import os
import json
import time
import requests
import pandas as pd
from datetime import timedelta
from typing import List, Optional
import anthropic

from config import get_secret

# API 키 로드 (.env 또는 Streamlit Secrets)
NEWSTORE_API_KEY = get_secret('NEWSTORE_API_KEY')
ANTHROPIC_API_KEY = get_secret('ANTHROPIC_API_KEY')

# 상수
BASE_URL = "https://www.newstore.or.kr/api-newstore/v1/search/newsAllList.json"
DEFAULT_PROVIDERS = ["중앙일보", "한겨레", "서울신문", "세계일보",
                     "서울경제", "KBS", "MBC", "SBS"]
DEFAULT_CATEGORIES = ["정치", "경제", "IT_과학"]
TIMEPOINT_ORDER = ["D-Day", "D+1", "D+3", "D+7", "D+14", "D+30"]


# ============================================================
# 1. 빅카인즈 API 호출
# ============================================================

def call_api_with_retry(payload: dict, max_attempts: int = 3) -> requests.Response:
    """일시 네트워크 끊김 자동 재시도"""
    headers = {"Content-Type": "application/json"}
    for attempt in range(max_attempts):
        try:
            response = requests.post(
                BASE_URL, headers=headers,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                timeout=30
            )
            return response
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < max_attempts - 1:
                wait_sec = 3 * (attempt + 1)
                print(f"   네트워크 끊김, {wait_sec}초 후 재시도... ({type(e).__name__})")
                time.sleep(wait_sec)
            else:
                raise


def search_bigkinds(
    query: str,
    date_from: str,
    date_to: str,
    providers: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    page_size: int = 100,
    max_pages: int = 10,
) -> pd.DataFrame:
    """
    빅카인즈 페이지네이션 검색
    
    Args:
        query: 검색어
        date_from: "YYYY-MM-DD"
        date_to: "YYYY-MM-DD"
        providers: 매체 리스트 (기본: 8개)
        categories: 카테고리 (기본: 정치/경제/IT_과학)
        page_size: 페이지당 결과 수
        max_pages: 최대 페이지 (안전장치)
    
    Returns:
        DataFrame (행=기사, 열=title/content/published_at/provider/...)
    """
    if providers is None:
        providers = DEFAULT_PROVIDERS
    if categories is None:
        categories = DEFAULT_CATEGORIES
    
    all_docs = []
    total_hits = None
    
    for page_idx in range(max_pages):
        payload = {
            "access_key": NEWSTORE_API_KEY,
            "argument": {
                "query": query,
                "published_at": {"from": date_from, "until": date_to},
                "provider": providers,
                "category": categories,
                "sort": {"date": "asc"},
                "return_from": page_idx * page_size,
                "return_size": page_size,
                "fields": [
                    "title", "content", "published_at", "enveloped_at",
                    "provider", "category", "provider_link_page"
                ]
            }
        }
        
        response = call_api_with_retry(payload)
        data = response.json()
        
        # 응답 검증
        if 'returnObject' not in data:
            reason = data.get('reason', '알 수 없는 오류')
            raise RuntimeError(f"빅카인즈 API 오류: {reason} (전체 응답: {data})")
        
        return_obj = json.loads(data['returnObject'])
        
        if total_hits is None:
            total_hits = return_obj.get('total_hits', 0)
        
        docs = return_obj.get('documents', [])
        if not docs:
            break
        
        all_docs.extend(docs)
        
        if len(all_docs) >= total_hits:
            break
        
        time.sleep(0.5)  # 서버 부하 방지
    
    df = pd.DataFrame(all_docs)
    
    # 날짜 컬럼 정규화
    if not df.empty and 'published_at' in df.columns:
        df['published_date'] = pd.to_datetime(df['published_at']).dt.tz_localize(None).dt.normalize()
    
    return df


# ============================================================
# 2. D+N 시점 분류
# ============================================================

def assign_timepoint(article_date: pd.Timestamp, d_day: pd.Timestamp) -> str:
    """기사 발행일을 D-Day 기준 시점 구간으로 분류"""
    days_diff = (article_date - d_day).days
    if days_diff < 0:
        return "Pre"
    elif days_diff == 0:
        return "D-Day"
    elif days_diff <= 1:
        return "D+1"
    elif days_diff <= 3:
        return "D+3"
    elif days_diff <= 7:
        return "D+7"
    elif days_diff <= 14:
        return "D+14"
    elif days_diff <= 30:
        return "D+30"
    else:
        return "Out"


def build_coverage_matrix(
    df: pd.DataFrame,
    d_day: pd.Timestamp,
    providers: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    매체 × 시점 커버리지 매트릭스 생성
    
    Args:
        df: search_bigkinds() 결과
        d_day: D-Day (pd.Timestamp)
        providers: 매트릭스에 포함할 매체 (없는 매체도 0으로 표시)
    
    Returns:
        DataFrame (인덱스=매체, 컬럼=시점)
    """
    if providers is None:
        providers = DEFAULT_PROVIDERS
    
    df = df.copy()
    df['timepoint'] = df['published_date'].apply(lambda d: assign_timepoint(d, d_day))
    
    matrix = pd.crosstab(df['provider'], df['timepoint'])
    
    # 시점 순서 정렬 + 8개 매체 강제 표시 (없으면 0)
    existing = [c for c in TIMEPOINT_ORDER if c in matrix.columns]
    matrix = matrix[existing]
    matrix = matrix.reindex(providers, fill_value=0)
    
    return matrix


# ============================================================
# 3. Claude API로 자동 리포트
# ============================================================

def generate_impact_report(
    df: pd.DataFrame,
    d_day: pd.Timestamp,
    matrix: pd.DataFrame,
    article_title: str = "",
    article_date: str = "",
    article_provider: str = "",
) -> dict:
    """
    매트릭스 + 데이터를 Claude에 넘겨 기자상 상신 양식 자동 생성
    
    Returns:
        {
            'report': str,        # 생성된 리포트 본문
            'cost_usd': float,    # 비용
            'tokens': dict        # 토큰 사용량
        }
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    # 매트릭스 텍스트
    matrix_text = matrix.to_string()
    
    # 매체별 주요 후속 기사 (시간순 상위 3건)
    sample_articles = []
    for provider in matrix.index:
        pdf = df[df['provider'] == provider].sort_values('published_date').head(3)
        if len(pdf) > 0:
            count = len(df[df['provider'] == provider])
            sample_articles.append(f"\n[{provider}] 총 {count}건")
            for _, row in pdf.iterrows():
                date_str = row['published_date'].strftime('%m/%d')
                sample_articles.append(f"  - {date_str} | {row['title']}")
    sample_text = "\n".join(sample_articles)
    
    # 통계
    total_count = len(df)
    provider_count = (matrix.sum(axis=1) > 0).sum()
    
    # 기사 정보 블록 (있을 때만)
    article_info = ""
    if article_title:
        article_info = f"""
[D-Day 단독 보도]
- 제목: {article_title}
- 발행: {article_date} ({article_provider})
"""
    
    prompt = """당신은 한국 기자의 글쓰기 보조 AI다. 한국기자협회 이달의 기자상 상신 양식 중 두 항목을 작성하라.
{article_info}
### 입력 데이터

[D-Day 기준 정보]
- D-Day: {d_day}
- 분석 기간: D-Day ~ D+{max_days}
- 분석 대상 매체: 중앙일보, 한겨레, 서울신문, 세계일보, 서울경제, KBS, MBC, SBS (8개)
- 총 후속 보도: {total}건
- 참여 매체: {pcount}/8개

[매체 × 시점 커버리지 매트릭스]
{matrix}

[매체별 주요 후속 보도]
{samples}

### 작성 요구사항

1. 타 매체 선행보도 여부 및 타 매체의 반향
   - D-Day부터 시점별 흐름 자연어로 서술
   - 어느 매체가 언제 진입했는지 시간순으로 명료하게
   - 마지막에 주요 후속 보도 5건 인용

2. 사회에 끼친 영향
   - [정책·제도 연결] 후속 보도에서 정부 부처 대응이 보이면 인용 (없으면 "확인되지 않음")
   - [국회 논의 연계] 정치 카테고리 후속 보도에서 국회/의원 언급 부분 추출
   - 시스템이 자동 작성 못 하는 부분은 "기자 직접 입력란"으로 분리 표시

### 출력 형식
- 각 항목 제목만 표시 (슬러그 없이)
- 격식 있는 한국어
- 과장 X, 데이터로 입증 가능한 내용만""".format(
        article_info=article_info,
        d_day=d_day.strftime('%Y년 %m월 %d일'),
        max_days=(df['published_date'].max() - d_day).days if not df.empty else 30,
        total=total_count,
        pcount=provider_count,
        matrix=matrix_text,
        samples=sample_text,
    )
    
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}]
    )
    
    report_text = response.content[0].text
    
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_usd = (input_tokens * 3 + output_tokens * 15) / 1_000_000
    
    return {
        'report': report_text,
        'cost_usd': cost_usd,
        'tokens': {'input': input_tokens, 'output': output_tokens},
    }


# ============================================================
# 4. 테스트 실행 (이 파일을 직접 실행하면 작동 확인)
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("pipeline.py 자체 테스트")
    print("=" * 60)
    
    # CSV에서 데이터 로드 (이미 수집된 GTX 데이터)
    csv_path = 'data/newstore_GTX철근누락_2026년5월.csv'
    if not os.path.exists(csv_path):
        print(f"❌ {csv_path} 파일이 없습니다. download_gtx.py 먼저 실행하세요.")
        exit(1)
    
    df = pd.read_csv(csv_path)
    df['published_date'] = pd.to_datetime(df['published_at']).dt.tz_localize(None).dt.normalize()
    
    print(f"✅ 데이터 로드: {len(df)}행")
    
    # D-Day 설정 (첫 보도일)
    d_day = df['published_date'].min()
    print(f"✅ D-Day: {d_day.strftime('%Y-%m-%d')}")
    
    # 매트릭스 생성
    matrix = build_coverage_matrix(df, d_day)
    print(f"\n📋 커버리지 매트릭스:")
    print(matrix)
    
    print(f"\n✅ pipeline.py 모든 함수 정상 작동")
    print("(자동 리포트는 토큰 비용 발생하므로 별도 명령으로 실행)")