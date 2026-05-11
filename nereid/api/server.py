"""
Nereid Hosted Server — self-hosted API for Google Drive folder watching.
Run with: uvicorn nereid.api.server:app --port 8000
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nereid.api.router import init_api

load_dotenv()

app = FastAPI(title="Nereid")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_api(app)