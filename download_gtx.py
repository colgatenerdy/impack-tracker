"""GTX 철근 누락 데이터 다운로드 (1회용 스크립트)"""
import requests
import json
import pandas as pd
import time
from dotenv import load_dotenv
import os

# .env에서 키 로드
load_dotenv()
API_KEY = os.getenv('NEWSTORE_API_KEY')

BASE_URL = "https://www.newstore.or.kr/api-newstore/v1/search/newsAllList.json"
PROVIDERS = ["중앙일보", "한겨레", "서울신문", "세계일보",
             "서울경제", "KBS", "MBC", "SBS"]

headers = {"Content-Type": "application/json"}


def call_api_with_retry(payload, max_attempts=3):
    """일시 네트워크 끊김 자동 재시도"""
    for attempt in range(max_attempts):
        try:
            response = requests.post(
                BASE_URL, headers=headers,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                timeout=30
            )
            return response
        except (requests.ConnectionError, requests.Timeout):
            if attempt < max_attempts - 1:
                print(f"   네트워크 끊김, {3 * (attempt + 1)}초 후 재시도...")
                time.sleep(3 * (attempt + 1))
            else:
                raise


# GTX 데이터 수집
gtx_payload = {
    "access_key": API_KEY,
    "argument": {
        "query": "GTX 누락",
        "published_at": {"from": "2026-05-15", "until": "2026-05-31"},
        "provider": PROVIDERS,
        "category": ["정치", "경제", "IT_과학"],
        "sort": {"date": "asc"},
        "return_size": 100,
        "fields": [
            "title", "content", "published_at", "enveloped_at",
            "provider", "category", "provider_link_page"
        ]
    }
}

all_docs = []
total_hits = None

print("===== GTX 철근 누락 데이터 수집 시작 =====\n")

for page_idx in range(5):
    gtx_payload['argument']['return_from'] = page_idx * 100
    response = call_api_with_retry(gtx_payload)
    data = response.json()
    print(f"\n[디버그] HTTP: {response.status_code}")
    print(f"[디버그] 응답: {data}\n")  # 응답 그대로 출력
    return_obj = json.loads(data['returnObject'])

    if total_hits is None:
        total_hits = return_obj['total_hits']
        print(f"전체: {total_hits}건\n")

    docs = return_obj.get('documents', [])
    if not docs:
        break

    all_docs.extend(docs)
    print(f"   페이지 {page_idx+1}: {len(docs)}건 (누적 {len(all_docs)})")

    if len(all_docs) >= total_hits:
        break

    time.sleep(0.5)

# DataFrame + CSV 저장
df = pd.DataFrame(all_docs)

# data 폴더 없으면 만들기
os.makedirs('data', exist_ok=True)

csv_path = 'data/newstore_GTX철근누락_2026년5월.csv'
df.to_csv(csv_path, index=False, encoding='utf-8-sig')

print(f"\n수집 완료: {len(df)}행")
print(f"저장: {csv_path}\n")
print("매체별:")
print(df['provider'].value_counts())