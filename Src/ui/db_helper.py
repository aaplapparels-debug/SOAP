import ssl
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from config_loader import load_config

@st.cache_resource
def get_engine():
    config = load_config()
    db_url = config["postgres"]["connection_string"]
    connect_args = {}
    
    # Smart detection: If local config uses pg8000, build the SSL object.
    if "pg8000" in db_url:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl_context"] = ctx
        
    return create_engine(db_url, poolclass=NullPool, connect_args=connect_args)
