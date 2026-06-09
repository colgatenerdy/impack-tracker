"""
config.py
API 키를 로컬(.env) 또는 Streamlit Cloud(Secrets) 어디서든 읽어오는 헬퍼
"""

import os
from dotenv import load_dotenv

load_dotenv()


def get_secret(key_name: str) -> str:
    """
    환경변수 또는 Streamlit Secrets에서 키 값을 읽어옴
    
    1. 로컬: .env 파일에서 읽음
    2. Streamlit Cloud: st.secrets에서 읽음
    """
    # 먼저 환경변수 시도 (로컬 .env)
    value = os.getenv(key_name)
    if value:
        return value
    
    # 환경변수에 없으면 Streamlit Secrets 시도 (배포 환경)
    try:
        import streamlit as st
        if key_name in st.secrets:
            return st.secrets[key_name]
    except Exception:
        pass
    
    raise ValueError(f"❌ {key_name} 을 찾을 수 없습니다. .env 또는 Streamlit Secrets를 확인하세요.")