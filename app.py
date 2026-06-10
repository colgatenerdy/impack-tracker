"""
app.py
기자 단독 보도 파급력 추적 시스템 - Streamlit 대시보드

페이지 흐름:
1. 입력 화면 — 기사 본문 + 발행일 입력
2. 키워드 편집 화면 — AI 추출 + 기자 수정
3. 결과 화면 — 매트릭스 + 자동 리포트
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from keyword_extractor import extract_keywords, build_search_query
from query_retry import smart_search


# ============================================================
# 페이지 설정
# ============================================================

st.set_page_config(
    page_title="기자 단독 보도 파급력 추적기",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.set_page_config(
    page_title="기자 단독 보도 파급력 추적기",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# 비밀번호 보호 (배포 환경에서만 작동)
# ============================================================

def check_password():
    """배포 시 비밀번호 입력 게이트"""
    try:
        # Streamlit Secrets에 APP_PASSWORD가 있을 때만 활성화 (로컬은 통과)
        if "APP_PASSWORD" not in st.secrets:
            return True
    except Exception:
        # 로컬 환경에서는 secrets 자체가 없어서 에러 → 통과
        return True
    
    if "password_correct" in st.session_state and st.session_state["password_correct"]:
        return True
    
    # 비밀번호 입력 UI
    st.title("📰 기자 단독 보도 파급력 추적기")
    st.caption("AI·SW대학원 김혜지 / A74007")
    st.divider()
    
    st.info(
        "🔒 본 시스템은 발표 평가용 비공개 데모입니다.\n\n"
        "접속 비밀번호를 입력해주세요."
    )
    
    password = st.text_input("비밀번호", type="password", key="password_input")
    
    if password:
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("❌ 비밀번호가 일치하지 않습니다.")
    
    return False


# 비밀번호 통과 안 하면 여기서 멈춤
if not check_password():
    st.stop()



# ============================================================
# 세션 상태 초기화
# ============================================================

if 'step' not in st.session_state:
    st.session_state.step = 1

if 'article_text' not in st.session_state:
    st.session_state.article_text = ""

if 'article_title' not in st.session_state:
    st.session_state.article_title = ""

if 'd_day' not in st.session_state:
    st.session_state.d_day = date(2026, 5, 16)

if 'article_provider' not in st.session_state:
    st.session_state.article_provider = "MBC"

if 'core_keywords' not in st.session_state:
    st.session_state.core_keywords = []

if 'frame_keywords' not in st.session_state:
    st.session_state.frame_keywords = []

if 'search_result' not in st.session_state:
    st.session_state.search_result = None


# ============================================================
# 헤더 + 진행 단계 표시
# ============================================================

st.markdown("""
<style>
    .step-box {
        padding: 8px 16px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
    }
    .step-active {
        background: #042C53;
        color: white;
    }
    .step-inactive {
        background: #F0F0F0;
        color: #999;
    }
    .step-done {
        background: #E1F5EE;
        color: #085041;
    }
    .stTextArea textarea {
        font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)

st.title("📰 기자 단독 보도 파급력 추적기")
st.caption("AI·SW대학원 김혜지 / A74007 · 빅카인즈 + Claude API 기반")


def render_step_indicator():
    steps = [
        (1, "1. 기사 입력"),
        (2, "2. 키워드 편집"),
        (3, "3. 추적 결과"),
    ]
    cols = st.columns(3)
    for i, (num, label) in enumerate(steps):
        with cols[i]:
            if st.session_state.step == num:
                st.markdown(f'<div class="step-box step-active" style="text-align:center;">{label}</div>',
                            unsafe_allow_html=True)
            elif st.session_state.step > num:
                st.markdown(f'<div class="step-box step-done" style="text-align:center;">✓ {label}</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="step-box step-inactive" style="text-align:center;">{label}</div>',
                            unsafe_allow_html=True)


render_step_indicator()
st.divider()


# ============================================================
# Step 1: 기사 입력 화면
# ============================================================

if st.session_state.step == 1:

    st.subheader("D-Day 기사 등록")
    st.caption(
        "추적하고 싶은 단독 보도를 등록하세요. **어떤 매체의 기사든 가능합니다.** "
        "본 시스템은 등록된 기사가 빅카인즈 8개 매체(중앙·한겨레·서울·세계·서울경제·KBS·MBC·SBS)에서 "
        "어떻게 후속 보도되었는지를 추적합니다."
    )

    col1, col2 = st.columns([3, 1])

    with col1:
        article_title = st.text_input(
            "기사 제목",
            value=st.session_state.article_title,
            placeholder="예: 단독 보도 기사의 제목을 입력하세요",
        )

    with col2:
        article_provider = st.text_input(
            "발행 매체",
            value=st.session_state.article_provider,
            placeholder="예: 한겨레, JTBC 등",
            help="어떤 매체든 입력 가능. 추적은 빅카인즈 8개 매체에서 진행됩니다.",
        )

    d_day = st.date_input(
        "D-Day (보도 발행일)",
        value=st.session_state.d_day,
        help="기사 발행일은 어떤 날짜든 입력 가능. 다만 빅카인즈 추적은 2026.5.1 ~ 2026.7.31 범위 내에서만 작동합니다.",
    )

    article_text = st.text_area(
        "기사 본문",
        value=st.session_state.article_text,
        height=300,
        placeholder="기사 본문을 붙여넣기 하세요...\n(AI가 자동으로 키워드를 추출해 빅카인즈에서 후속 보도를 추적합니다)",
        help="최소 100자 이상 권장.",
    )

    char_count = len(article_text)
    if char_count == 0:
        st.caption("📝 0자 입력됨")
    elif char_count < 100:
        st.caption(f"⚠️ {char_count}자 — 100자 이상 권장")
    else:
        st.caption(f"✅ {char_count}자 입력됨")

    st.divider()

    with st.expander("📚 검증된 사례로 빠르게 시작", expanded=False):
        st.write("아래 검증된 사례를 불러와 시스템 작동을 즉시 확인할 수 있습니다.")
        if st.button("📰 MBC 단독 — GTX-A 철근 누락 (2026.5)", use_container_width=True):
            st.session_state.article_title = "[단독] 영동대로 지하복합개발 삼성역 승강장 기둥에 철근 절반만 넣어"
            st.session_state.article_provider = "MBC"
            st.session_state.d_day = date(2026, 5, 16)
            st.session_state.article_text = """MBC 취재 결과, GTX-A 노선의 핵심 환승 거점인 영동대로 삼성역 복합환승센터 공사 현장에서 시공사인 현대건설이 일부 기둥에 설계도면상 명시된 철근의 절반만 시공한 사실이 드러났다.

서울시 관계자에 따르면, 해당 부실 시공은 지하 4층 승강장 부분 기둥 3곳에서 발견됐으며, 이는 안전 설계 기준을 크게 미달하는 수준이다. 서울시는 즉시 시공 중단을 지시하고 자체 감사에 착수했다.

국토교통부도 별도 실태조사를 검토하고 있다고 밝혔다. 현대건설 측은 "단순 시공 실수이며, 즉시 재시공할 예정"이라고 해명했지만, 6·3 지방선거를 앞두고 서울시장 후보 간 핵심 쟁점으로 부상하고 있다."""
            st.rerun()

    col1, col2, col3 = st.columns([1, 1, 1])
    with col3:
        next_disabled = char_count < 50 or not article_title.strip()
        if st.button("키워드 추출 →", type="primary", disabled=next_disabled, use_container_width=True):
            st.session_state.article_title = article_title
            st.session_state.article_provider = article_provider
            st.session_state.d_day = d_day
            st.session_state.article_text = article_text
            st.session_state.step = 2
            st.rerun()


# ============================================================
# Step 2: 키워드 편집 화면
# ============================================================

elif st.session_state.step == 2:

    if not st.session_state.core_keywords and not st.session_state.frame_keywords:
        with st.spinner("🤖 AI가 기사를 분석해 검색 키워드를 추출 중... (10초 정도)"):
            try:
                result = extract_keywords(st.session_state.article_text)
                st.session_state.core_keywords = result['core']
                st.session_state.frame_keywords = result['frames']
                st.session_state.extract_reasoning = result.get('reasoning', '')
                st.session_state.extract_cost = result.get('cost_usd', 0)
            except Exception as e:
                st.error(f"키워드 추출 실패: {e}")
                st.stop()

    st.info("""
    💡 **이 화면이 본 시스템의 핵심입니다.**  
    AI는 기사 본문에 있는 표현만 추출합니다. 그러나 후속 보도는 종종 새로운 프레임 단어 
    (예: '순살 시공', '졸속 입법')로 확산됩니다. 기자가 직접 키워드를 편집해 
    **AI 자동화와 도메인 지식을 결합**할 수 있습니다.
    """)

    if st.session_state.get('extract_reasoning'):
        with st.expander("🤖 AI 추출 근거 보기"):
            st.caption(st.session_state.extract_reasoning)
            if st.session_state.get('extract_cost'):
                st.caption(f"💰 AI 호출 비용: ${st.session_state.extract_cost:.4f} "
                           f"(약 {st.session_state.extract_cost * 1400:.0f}원)")

    st.divider()

    # Core 키워드
    st.subheader("🟦 AI 자동 추출 키워드")
    st.caption("기사 본문에서 추출됨 — 클릭으로 삭제 가능")

    if st.session_state.core_keywords:
        cols = st.columns(len(st.session_state.core_keywords))
        for i, kw in enumerate(st.session_state.core_keywords):
            with cols[i]:
                if st.button(f"❌ {kw}", key=f"core_{i}", use_container_width=True):
                    st.session_state.core_keywords.pop(i)
                    st.rerun()
    else:
        st.warning("키워드가 모두 삭제되었습니다.")

    col1, col2 = st.columns([3, 1])
    with col1:
        new_core = st.text_input("Core 키워드 추가", key="new_core_input",
                                  placeholder="예: 영동대로", label_visibility="collapsed")
    with col2:
        if st.button("➕ Core 추가", use_container_width=True):
            if new_core.strip() and new_core.strip() not in st.session_state.core_keywords:
                st.session_state.core_keywords.append(new_core.strip())
                st.rerun()

    st.divider()

    # Frames 키워드
    st.subheader("🟩 확산 프레임 후보")
    st.caption("본문에 없지만 후속 보도에서 등장할 가능성 있는 표현 — 기자 도메인 지식으로 추가하세요")

    if st.session_state.frame_keywords:
        cols = st.columns(min(len(st.session_state.frame_keywords), 4))
        for i, kw in enumerate(st.session_state.frame_keywords):
            with cols[i % 4]:
                if st.button(f"❌ {kw}", key=f"frame_{i}", use_container_width=True):
                    st.session_state.frame_keywords.pop(i)
                    st.rerun()
    else:
        st.caption("_(아직 추가된 프레임 없음)_")

    col1, col2 = st.columns([3, 1])
    with col1:
        new_frame = st.text_input("Frame 키워드 추가", key="new_frame_input",
                                   placeholder="예: 순살 시공", label_visibility="collapsed")
    with col2:
        if st.button("➕ Frame 추가", use_container_width=True):
            if new_frame.strip() and new_frame.strip() not in st.session_state.frame_keywords:
                st.session_state.frame_keywords.append(new_frame.strip())
                st.rerun()

    st.divider()

    # 검색 쿼리 미리보기
    st.subheader("🔍 빅카인즈 검색 쿼리 (자동 생성)")

    query_preview = build_search_query(
        st.session_state.core_keywords,
        st.session_state.frame_keywords,
    )

    if query_preview:
        st.code(query_preview, language="text")

        from datetime import date as date_type
        license_end = date_type(2026, 7, 31)
        d_plus_30 = st.session_state.d_day + timedelta(days=30)
        date_to_preview = min(d_plus_30, license_end)

        total_kw = len(st.session_state.core_keywords) + len(st.session_state.frame_keywords)
        st.caption(f"📊 총 {total_kw}개 키워드 OR 결합 | 추적 기간: "
                   f"{st.session_state.d_day.strftime('%Y-%m-%d')} ~ "
                   f"{date_to_preview.strftime('%Y-%m-%d')}")
    else:
        st.warning("⚠️ 키워드를 하나 이상 입력해주세요.")

    st.divider()

    # 네비게이션
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("← 이전", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
    with col3:
        next_disabled = not query_preview
        if st.button("추적 시작 →", type="primary", disabled=next_disabled, use_container_width=True):
            st.session_state.step = 3
            st.session_state.search_result = None
            st.rerun()


# ============================================================
# Step 3: 추적 결과 화면
# ============================================================

elif st.session_state.step == 3:

    from pipeline import build_coverage_matrix, generate_impact_report
    import matplotlib.pyplot as plt
    import seaborn as sns
    from io import BytesIO
    from datetime import date as date_type

    import matplotlib.font_manager as fm
    import os

    # Streamlit Cloud용 한글 폰트 직접 등록
    # packages.txt로 깐 NanumGothic 경로를 강제로 지정
    nanum_paths = [
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf',
    ]
    for path in nanum_paths:
        if os.path.exists(path):
            fm.fontManager.addfont(path)
    
    # 폰트 캐시 강제 재구축
    try:
        fm._load_fontmanager(try_read_cache=False)
    except Exception:
        pass
    
    # 사용 가능한 폰트 중 한글 폰트 선택
    font_candidates = ['NanumGothic', 'NanumBarunGothic', 'Malgun Gothic', 'AppleGothic']
    available_fonts = {f.name for f in fm.fontManager.ttflist}
    
    selected_font = None
    for font in font_candidates:
        if font in available_fonts:
            selected_font = font
            break
    
    if selected_font:
        plt.rcParams['font.family'] = selected_font
        plt.rcParams['font.sans-serif'] = [selected_font]
    
    plt.rcParams['axes.unicode_minus'] = False

    d_day = pd.Timestamp(st.session_state.d_day)

    # 검색 실행
    if st.session_state.search_result is None:
        with st.spinner("🔍 빅카인즈에서 후속 보도 추적 중... (1~2분 소요)"):
            try:
                date_from = st.session_state.d_day.strftime('%Y-%m-%d')
                # D+30 또는 이용허락 종료일(7/31) 중 빠른 것
                license_end = date_type(2026, 7, 31)
                d_plus_30 = st.session_state.d_day + timedelta(days=30)
                date_to = min(d_plus_30, license_end).strftime('%Y-%m-%d')

                df_result, meta = smart_search(
                    core_keywords=st.session_state.core_keywords,
                    frame_keywords=st.session_state.frame_keywords,
                    date_from=date_from,
                    date_to=date_to,
                    verbose=False,
                )

                st.session_state.search_result = df_result
                st.session_state.search_meta = meta
            except Exception as e:
                error_msg = str(e)
                # 이용허락 범위 밖 에러를 친절하게 안내
                if "이용조건" in error_msg or "권한" in error_msg or "5001" in error_msg:
                    st.error(
                        "⚠️ **빅카인즈 이용허락 범위를 벗어났습니다.**\n\n"
                        "본 시연 시스템은 2026.5.1 ~ 2026.7.31 기간의 데이터만 추적 가능합니다. "
                        "D-Day를 해당 기간 내로 다시 설정해주세요."
                    )
                else:
                    st.error(f"검색 실패: {error_msg[:200]}")
                
                if st.button("← 키워드 편집으로 돌아가기"):
                    st.session_state.step = 2
                    st.session_state.search_result = None
                    st.rerun()
                st.stop()

    df_result = st.session_state.search_result
    meta = st.session_state.search_meta

    if df_result.empty:
        st.error("❌ 검색 결과가 없습니다. 키워드를 다시 조정해주세요.")
        if st.button("← 키워드 편집으로"):
            st.session_state.step = 2
            st.rerun()
        st.stop()

    # 요약 카드
    st.subheader("📊 추적 결과 요약")

    total_count = len(df_result)
    matrix = build_coverage_matrix(df_result, d_day)
    provider_count = (matrix.sum(axis=1) > 0).sum()

    later = df_result[df_result['published_date'] > d_day]
    if len(later) > 0:
        first_followup = later.sort_values('published_date').iloc[0]
        first_str = f"{first_followup['provider']}"
        first_days = (first_followup['published_date'] - d_day).days
    else:
        first_str = "N/A"
        first_days = 0

    broadcast = ['KBS', 'MBC', 'SBS']
    broadcast_in = sum(1 for b in broadcast if b in matrix.index and matrix.loc[b].sum() > 0)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 후속 보도", f"{total_count}건")
    col2.metric("참여 매체", f"{provider_count}/8개")
    col3.metric("첫 후속", first_str, f"D+{first_days}일")
    col4.metric("방송 3사", f"{broadcast_in}/3개")

    st.divider()

    # 매트릭스 히트맵
    st.subheader("📋 매체 × 시점 커버리지 매트릭스")
    st.caption("세로축 = 매체, 가로축 = D-Day로부터의 시점, 색상 진하기 = 보도량")

    fig, ax = plt.subplots(figsize=(11, 5))

    matrix_viz = matrix.drop(columns=['Out', 'Pre'], errors='ignore')

    sns.heatmap(
        matrix_viz, annot=True, fmt='d', cmap='Reds',
        cbar_kws={'label': '기사 건수'},
        linewidths=1, linecolor='white',
        annot_kws={'size': 12, 'weight': 'bold'},
        ax=ax
    )

    for i in range(matrix_viz.shape[0]):
        for j in range(matrix_viz.shape[1]):
            if matrix_viz.iloc[i, j] == 0:
                ax.add_patch(plt.Rectangle((j, i), 1, 1,
                                            facecolor='#F0F0F0',
                                            edgecolor='white', lw=1))
                ax.text(j+0.5, i+0.5, '-', ha='center', va='center',
                       color='#999999', fontsize=12)

    title_text = st.session_state.article_title[:40]
    if len(st.session_state.article_title) > 40:
        title_text += "..."

    ax.set_title(
        f"{title_text}\n"
        f"D-Day: {d_day.strftime('%Y-%m-%d')} · 총 {total_count}건",
        fontsize=12, pad=15, weight='bold'
    )
    ax.set_xlabel('추적 시점', fontsize=11)
    ax.set_ylabel('매체', fontsize=11)
    plt.tight_layout()

    st.pyplot(fig)

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    st.download_button(
        "📥 매트릭스 이미지 다운로드 (PNG)",
        data=buf.getvalue(),
        file_name=f"coverage_matrix_{d_day.strftime('%Y%m%d')}.png",
        mime="image/png",
    )

    st.divider()

    # 자동 리포트
    st.subheader("📰 한국기자협회 상신 양식 — 자동 생성")

    if 'report_result' not in st.session_state or st.session_state.get('report_for_step') != st.session_state.step:
        if st.button("🤖 Claude로 상신 양식 자동 생성하기", type="primary"):
            with st.spinner("🤖 Claude가 상신 양식 작성 중... (15~20초)"):
                try:
                    report_result = generate_impact_report(
                        df=df_result,
                        d_day=d_day,
                        matrix=matrix,
                        article_title=st.session_state.article_title,
                        article_date=d_day.strftime('%Y-%m-%d'),
                        article_provider=st.session_state.article_provider,
                    )
                    st.session_state.report_result = report_result
                    st.session_state.report_for_step = st.session_state.step
                    st.rerun()
                except Exception as e:
                    st.error(f"리포트 생성 실패: {e}")
    else:
        report = st.session_state.report_result
        st.markdown(report['report'])
        st.divider()
        st.caption(
            f"💰 생성 비용: ${report['cost_usd']:.4f} (약 {report['cost_usd'] * 1400:.0f}원) | "
            f"토큰: 입력 {report['tokens']['input']}, 출력 {report['tokens']['output']}"
        )
        st.download_button(
            "📥 리포트 텍스트 다운로드 (.txt)",
            data=report['report'],
            file_name=f"report_{d_day.strftime('%Y%m%d')}.txt",
            mime="text/plain",
        )

    st.divider()

    # 후속 보도 리스트
    with st.expander(f"📰 전체 후속 보도 리스트 ({total_count}건)"):
        df_display = df_result[['published_date', 'provider', 'title']].copy()
        df_display['published_date'] = df_display['published_date'].dt.strftime('%Y-%m-%d')
        df_display.columns = ['발행일', '매체', '제목']
        df_display = df_display.sort_values('발행일')
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        csv = df_display.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            "📥 후속 보도 리스트 (.csv)",
            data=csv,
            file_name=f"followups_{d_day.strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )

    st.divider()

    # 네비게이션
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("← 키워드 편집", use_container_width=True):
            st.session_state.step = 2
            st.session_state.search_result = None
            if 'report_result' in st.session_state:
                del st.session_state['report_result']
            st.rerun()
    with col3:
        if st.button("🔄 처음으로 (새 기사)", use_container_width=True):
            for key in ['step', 'article_text', 'article_title', 'core_keywords',
                        'frame_keywords', 'search_result', 'report_result']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()