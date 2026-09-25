#!/usr/bin/env python3
"""
Production Environment Configuration Generator for Dograh Enterprise SaaS.

Generates a cryptographically secure .env file for production deployments
with all necessary secrets, database credentials, MinIO access keys,
TURN configuration, and VoiceStudio / tiered inference settings.

Usage:
    python scripts/generate_prod_env.py [--output .env.production] [--domain voice.yourdomain.com]
"""

import argparse
import secrets
import sys
from pathlib import Path


def generate_secret(nbytes: int = 32) -> str:
    """Generate a cryptographically secure hex secret."""
    return secrets.token_hex(nbytes)


def generate_password(length: int = 24) -> str:
    """Generate a URL-safe secure password."""
    return secrets.token_urlsafe(length)


def build_prod_env(domain: str, workers: int, enable_signup: bool, voicestudio_device: str) -> str:
    jwt_secret = generate_secret(32)
    devops_secret = generate_secret(32)
    pg_password = generate_password(24)
    redis_password = generate_password(24)
    minio_user = f"dograh_{secrets.token_hex(6)}"
    minio_password = generate_password(24)
    turn_secret = generate_secret(32)
    telephony_token = generate_secret(32)

    public_base_url = f"https://{domain}" if domain != "localhost" else "http://localhost:3000"
    public_host = domain

    template = f"""# ==============================================================================
# Dograh Enterprise SaaS - Production Environment Configuration
# Generated with scripts/generate_prod_env.py
# ==============================================================================

# Core Application Environment
ENVIRONMENT=production
LOG_LEVEL=INFO
ENABLE_SIGNUP={"true" if enable_signup else "false"}
FASTAPI_WORKERS={workers}
FORWARDED_ALLOW_IPS=*

# Public Domain / Ingress Routing
PUBLIC_HOST={public_host}
PUBLIC_BASE_URL={public_base_url}
BACKEND_API_ENDPOINT={public_base_url}
MINIO_PUBLIC_ENDPOINT={public_base_url}

# Authentication & DevOps Security
OSS_JWT_SECRET={jwt_secret}
DOGRAH_DEVOPS_SECRET={devops_secret}

# Database (PostgreSQL 17 + pgvector)
POSTGRES_USER=postgres
POSTGRES_PASSWORD={pg_password}
POSTGRES_DB=postgres
DATABASE_URL=postgresql+asyncpg://postgres:{pg_password}@postgres:5432/postgres

# Caching & Background Task Queue (Redis 7)
REDIS_PASSWORD={redis_password}
REDIS_URL=redis://:{redis_password}@redis:6379

# Storage (MinIO S3-Compatible)
MINIO_ROOT_USER={minio_user}
MINIO_ROOT_PASSWORD={minio_password}
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY={minio_user}
MINIO_SECRET_KEY={minio_password}
MINIO_BUCKET=voice-audio
MINIO_SECURE=false

# Tiered Inference Pipeline: VoiceStudio Local Synthesis
VOICESTUDIO_API_URL=http://voicestudio:8080
VOICESTUDIO_DEVICE={voicestudio_device}

# Telephony & WebRTC Signaling
ENABLE_COTURN=true
TURN_HOST={public_host}
TURN_SECRET={turn_secret}
FORCE_TURN_RELAY=false
TELEPHONY_WS_TOKEN_SECRET={telephony_token}
TELEPHONY_WS_TOKEN_ENFORCE=true

# Telemetry
ENABLE_TELEMETRY=false
"""
    return template


def main():
    parser = argparse.ArgumentParser(description="Generate production environment secrets and configuration.")
    parser.add_argument("--output", "-o", default=".env.production", help="Path to write the production env file (default: .env.production)")
    parser.add_argument("--domain", "-d", default="voice.example.com", help="Primary public domain for the platform (e.g. voice.dograh.ai)")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Number of FastAPI uvicorn workers (default: 4)")
    parser.add_argument("--allow-signup", action="store_true", help="Enable public signups (default: false / invite-only)")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu", help="Compute device for VoiceStudio TTS container (default: cpu)")
    parser.add_argument("--force", "-f", action="store_true", help="Overwrite output file if it already exists")

    args = parser.parse_args()

    out_path = Path(args.output).resolve()
    if out_path.exists() and not args.force:
        print(f"Error: Output file '{out_path}' already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    content = build_prod_env(
        domain=args.domain,
        workers=args.workers,
        enable_signup=args.allow_signup,
        voicestudio_device=args.device,
    )

    out_path.write_text(content, encoding="utf-8")
    print(f"[OK] Production environment generated at: {out_path}")
    print(f"     Domain: {args.domain}")
    print(f"     FastAPI Workers: {args.workers}")
    print(f"     VoiceStudio Device: {args.device}")
    print("=" * 60)
    print("To launch production stack with these settings:")
    print(f"  docker compose --env-file {args.output} up -d")
    print("=" * 60)


if __name__ == "__main__":
    main()
