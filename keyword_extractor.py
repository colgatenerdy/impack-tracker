"""
keyword_extractor.py
기사 본문에서 빅카인즈 검색 쿼리를 자동 추출하는 모듈

주요 함수:
- extract_keywords(article_text) → {core: [...], frames: [...]}
- build_search_query(core_keywords, frame_keywords) → 빅카인즈 쿼리 문자열
"""

import json
import re
from typing import List
import anthropic
from config import get_secret

ANTHROPIC_API_KEY = get_secret('ANTHROPIC_API_KEY')


# ============================================================
# 1. Claude로 키워드 추출
# ============================================================

def extract_keywords(article_text: str, max_core: int = 5, max_frames: int = 3) -> dict:
    """
    기사 본문에서 빅카인즈 검색용 키워드를 두 종류로 추출
    
    Args:
        article_text: 기사 본문 (제목 + 본문, 100자 이상 권장)
        max_core: 핵심 키워드 최대 개수
        max_frames: 확산 프레임 후보 최대 개수
    
    Returns:
        {
            'core': [...],        # AI가 본문에서 추출한 핵심 키워드
            'frames': [...],      # 후속 보도 확산 프레임 후보
            'reasoning': str      # Claude의 판단 근거 (디버깅용)
        }
    """
    if not article_text or len(article_text.strip()) < 50:
        raise ValueError("기사 본문이 너무 짧습니다 (최소 50자).")
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    # 기사가 너무 길면 앞부분만 (Claude 토큰 절약)
    article_excerpt = article_text[:3000]
    
    prompt = """당신은 한국 언론사 기자의 보조 AI다. 입력된 기사를 분석해 빅카인즈에서 후속 보도를 검색하는 데 사용할 키워드를 두 종류로 추출하라.

### 입력 기사
{article}

### 작성 요구사항

**1. core 키워드 (본문에 있는 핵심 식별자, 최대 {max_core}개)**
- 본문에서 실제로 등장하는 고유명사·법안명·기관명·인물명·핵심 사건명
- 너무 일반적인 단어(예: "정부", "발표", "관계자")는 제외
- 너무 좁은 표현(전체 문장이나 5자 이상 긴 구문)은 제외
- 빅카인즈가 인식 가능한 한국어 표현 우선

**2. frames 키워드 (확산 프레임 후보, 최대 {max_frames}개)**
- 본문엔 없지만 후속 보도에서 등장할 가능성 높은 프레임 표현
- 예: 부실시공 이슈 → "순살 시공" / AI 규제 이슈 → "졸속 입법"
- 정치권·시민사회·업계가 사용할 만한 일반화된 호명 방식
- 추측 기반이므로 신중하게 (없으면 빈 배열도 OK)

**3. reasoning (한 문장)**
- 위 키워드를 왜 골랐는지 짧게 설명

### 출력 형식 (반드시 JSON, 다른 설명 없이)
{{
  "core": ["키워드1", "키워드2", ...],
  "frames": ["프레임1", "프레임2"],
  "reasoning": "한 줄 근거"
}}""".format(
        article=article_excerpt,
        max_core=max_core,
        max_frames=max_frames,
    )
    
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    
    response_text = response.content[0].text.strip()
    
    # JSON 파싱 (Claude가 가끔 ```json ... ``` 으로 감쌀 수 있음)
    json_match = re.search(r'\{[^{}]*"core"[^{}]*\}', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group()
    else:
        # 백틱 제거 시도
        json_str = re.sub(r'^```(?:json)?\s*|\s*```$', '', response_text, flags=re.MULTILINE)
    
    try:
        result = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude 응답이 JSON이 아님: {response_text[:500]}")
    
    # 검증
    if 'core' not in result:
        result['core'] = []
    if 'frames' not in result:
        result['frames'] = []
    if 'reasoning' not in result:
        result['reasoning'] = ''
    
    # 비용 계산
    cost_usd = (
        response.usage.input_tokens * 3 + 
        response.usage.output_tokens * 15
    ) / 1_000_000
    result['cost_usd'] = cost_usd
    result['tokens'] = {
        'input': response.usage.input_tokens,
        'output': response.usage.output_tokens,
    }
    
    return result


# ============================================================
# 2. 키워드 → 빅카인즈 검색 쿼리
# ============================================================

def build_search_query(
    core_keywords: List[str],
    frame_keywords: List[str] = None,
) -> str:
    """
    키워드 리스트를 빅카인즈 검색 쿼리로 변환 (네이버식 AND 검색)
    
    빅카인즈는 공백 = AND 로 인식.
    "GTX 철근" 같이 공백 포함 키워드는 → AND 검색 (두 단어 모두 포함된 기사)
    "현대건설" 같이 단일 단어는 → 그 단어 들어간 기사
    여러 키워드는 OR 결합 (하나라도 매칭되면 잡힘)
    
    Args:
        core_keywords: ["GTX 철근", "현대건설", ...]
        frame_keywords: ["순살 시공", "부실시공"]
    
    Returns:
        '(GTX 철근) OR 현대건설 OR (순살 시공) OR 부실시공'
    """
    if frame_keywords is None:
        frame_keywords = []
    
    all_keywords = list(core_keywords) + list(frame_keywords)
    all_keywords = [k.strip() for k in all_keywords if k and k.strip()]
    
    if not all_keywords:
        return ""
    
    # 공백 있으면 괄호로 묶어서 AND 명시
    # 공백 없으면 단일 단어 그대로
    processed = []
    for kw in all_keywords:
        if ' ' in kw:
            processed.append(f'({kw})')
        else:
            processed.append(kw)
    
    query = " OR ".join(processed)
    return query


# ============================================================
# 3. 테스트
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("keyword_extractor.py 자체 테스트")
    print("=" * 60)
    
    # GTX 단독 보도 가상 본문 (시연용)
    sample_article = """
[단독] 영동대로 지하복합개발 삼성역 승강장 기둥에 철근 절반만 넣어

MBC 취재 결과, GTX-A 노선의 핵심 환승 거점인 영동대로 삼성역 
복합환승센터 공사 현장에서 시공사인 현대건설이 일부 기둥에 
설계도면상 명시된 철근의 절반만 시공한 사실이 드러났다.

서울시는 이번 사실을 인지한 직후 자체 감사에 착수했으며, 
국토교통부도 별도 실태조사를 검토하고 있다고 밝혔다. 
현대건설 측은 "단순 시공 실수"라고 해명했지만, 
6·3 지방선거를 앞두고 서울시장 선거 핵심 쟁점으로 부상하고 있다.
"""
    
    print("\n📰 입력 기사 (앞부분):")
    print(sample_article[:200] + "...\n")
    
    print("⏳ Claude 호출 중... (10초 정도)")
    
    result = extract_keywords(sample_article)
    
    print("\n" + "=" * 60)
    print("📋 추출 결과")
    print("=" * 60)
    
    print(f"\n[Core 키워드 — AI 자동 추출]")
    for kw in result['core']:
        print(f"  • {kw}")
    
    print(f"\n[Frames 키워드 — 확산 프레임 후보]")
    for kw in result['frames']:
        print(f"  • {kw}")
    
    print(f"\n[Reasoning]")
    print(f"  {result['reasoning']}")
    
    print(f"\n[비용]")
    print(f"  ${result['cost_usd']:.4f} (약 {result['cost_usd']*1400:.0f}원)")
    print(f"  토큰: 입력 {result['tokens']['input']}, 출력 {result['tokens']['output']}")
    
    # 검색 쿼리 생성 테스트
    query = build_search_query(result['core'], result['frames'])
    print(f"\n[빅카인즈 검색 쿼리]")
    print(f"  {query}")
    
    print("\n✅ keyword_extractor.py 정상 작동")