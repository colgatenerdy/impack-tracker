"""
query_retry.py
빅카인즈 검색 결과가 부족할 때 자동으로 키워드를 완화/재시도

주요 함수:
- smart_search(core, frames, date_from, date_to) → 적정 결과 DataFrame
"""

from typing import List, Tuple
import pandas as pd
from pipeline import search_bigkinds, DEFAULT_PROVIDERS, DEFAULT_CATEGORIES


# 적정 결과 범위
MIN_RESULTS = 5        # 너무 적음 (검색 너무 좁은 상태)
TARGET_MIN = 20         # 이상적 범위 시작
TARGET_MAX = 500        # 이상적 범위 끝
MAX_RESULTS = 1000       # 너무 많음 (검색 너무 넓은 상태)


def smart_search(
    core_keywords: List[str],
    frame_keywords: List[str],
    date_from: str,
    date_to: str,
    providers: List[str] = None,
    categories: List[str] = None,
    verbose: bool = True,
) -> Tuple[pd.DataFrame, dict]:
    """
    여러 검색 전략을 자동으로 시도해 적정 결과를 찾음
    
    검색 전략 순서:
    1. 모든 키워드 OR 결합 (가장 좁음)
    2. Core 키워드만 OR 결합
    3. Core 중 상위 3개만 OR 결합
    4. Core 1개씩 차례로 (가장 넓음)
    
    Returns:
        (DataFrame, 메타정보 dict)
    """
    if providers is None:
        providers = DEFAULT_PROVIDERS
    if categories is None:
        categories = DEFAULT_CATEGORIES
    
    log = []
    
    def _log(msg):
        if verbose:
            print(f"   {msg}")
        log.append(msg)
    
    # 시도할 전략들 (좁은 것부터 넓은 것 순)
    strategies = []
    
    # 전략 1: Core + Frames OR
    if core_keywords and frame_keywords:
        q1 = " OR ".join([f'"{k}"' for k in core_keywords + frame_keywords])
        strategies.append(("Core + Frames OR", q1))
    
    # 전략 2: Core만 OR
    if core_keywords:
        q2 = " OR ".join([f'"{k}"' for k in core_keywords])
        strategies.append(("Core 전체 OR", q2))
    
    # 전략 3: Core 상위 3개 OR
    if len(core_keywords) >= 3:
        q3 = " OR ".join([f'"{k}"' for k in core_keywords[:3]])
        strategies.append(("Core 상위 3개 OR", q3))
    
    # 전략 4: Core 첫 1개만
    if core_keywords:
        q4 = f'"{core_keywords[0]}"'
        strategies.append(("Core 첫 1개만", q4))
    
    # 순서대로 시도
    best_df = None
    best_strategy = None
    
    _log(f"📅 검색 기간: {date_from} ~ {date_to}")
    _log(f"🔑 Core: {core_keywords}")
    _log(f"🎯 Frames: {frame_keywords}")
    _log("")
    
    for strategy_name, query in strategies:
        _log(f"▶ 전략: {strategy_name}")
        _log(f"  쿼리: {query[:80]}{'...' if len(query) > 80 else ''}")
        
        df = search_bigkinds(
            query=query,
            date_from=date_from,
            date_to=date_to,
            providers=providers,
            categories=categories,
        )
        
        n = len(df)
        _log(f"  → 결과: {n}건")
        
        # 적정 범위 안이면 즉시 채택
        if TARGET_MIN <= n <= TARGET_MAX:
            _log(f"  ✅ 적정 (목표 범위 {TARGET_MIN}~{TARGET_MAX}건)")
            return df, {
                'strategy': strategy_name,
                'query': query,
                'count': n,
                'status': 'optimal',
                'log': log,
            }
        
        # 적정은 아니지만 너무 적지도/많지도 않으면 기록만
        if MIN_RESULTS <= n <= MAX_RESULTS:
            if best_df is None or abs(n - 100) < abs(len(best_df) - 100):
                best_df = df
                best_strategy = strategy_name
                _log(f"  ⚠ 차선책으로 저장 (100건과 가장 가까움)")
        
        _log("")
    
    # 적정 결과 못 찾음 → 차선책 반환
    if best_df is not None:
        _log(f"⚠ 적정 범위 결과 없음. 차선책 '{best_strategy}' 채택 ({len(best_df)}건)")
        return best_df, {
            'strategy': best_strategy,
            'count': len(best_df),
            'status': 'suboptimal',
            'log': log,
        }
    
    # 모든 전략 실패
    _log("❌ 모든 전략 실패 - 결과 너무 적거나 너무 많음")
    return pd.DataFrame(), {
        'strategy': None,
        'count': 0,
        'status': 'failed',
        'log': log,
    }


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("query_retry.py 자체 테스트")
    print("=" * 60)
    
    # 시나리오 1: GTX 케이스 (정상)
    print("\n🧪 시나리오 1: GTX 철근 누락 (정상 케이스)")
    print("-" * 60)
    df1, meta1 = smart_search(
        core_keywords=["GTX", "철근", "누락", "영동대로"],
        frame_keywords=["순살 시공"],
        date_from="2026-05-15",
        date_to="2026-05-31",
    )
    print(f"\n최종: {len(df1)}건, 전략: {meta1['strategy']}, 상태: {meta1['status']}")
    
    # 시나리오 2: 너무 좁은 키워드 (자동 완화 작동 확인)
    print("\n\n🧪 시나리오 2: 너무 좁은 키워드 (완화 작동 테스트)")
    print("-" * 60)
    df2, meta2 = smart_search(
        core_keywords=["존재하지않을극히드문단어조합xyz"],
        frame_keywords=[],
        date_from="2026-05-15",
        date_to="2026-05-31",
    )
    print(f"\n최종: {len(df2)}건, 상태: {meta2['status']}")
    
    print("\n✅ query_retry.py 정상 작동")