"""Seed the database with initial data for development."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
from app.core.database import SessionLocal, engine, Base
from app.core.auth import hash_password
from app.models.incident import (
    User, Repository, Service, Incident, IncidentStatus, IncidentSeverity, IncidentSource,
    Investigation, InvestigationStatus, Confidence,
)

# Create tables
Base.metadata.create_all(bind=engine)

db = SessionLocal()

try:
    existing = db.query(User).filter(User.username == "admin").first()
    if not existing:
        # --- Users ---
        admin = User(
            username="admin",
            email="admin@sentinel.dev",
            hashed_password=hash_password("sentinel123"),
        )
        db.add(admin)
        db.flush()

        # --- Services ---
        services = [
            Service(name="payment-api", description="Payment processing API"),
            Service(name="auth-api", description="Authentication service"),
            Service(name="core-api-gateway", description="API gateway"),
            Service(name="billing-api", description="Billing and invoicing"),
            Service(name="fraud-service", description="Fraud detection"),
        ]
        db.add_all(services)
        db.flush()

        # --- Repositories ---
        repos = [
            Repository(name="payment-service", full_name="acme-corp/payment-service",
                       owner_id=admin.id, service_id=services[0].id),
            Repository(name="payment-common", full_name="acme-corp/payment-common",
                       owner_id=admin.id, service_id=services[0].id),
            Repository(name="auth-api", full_name="acme-corp/auth-api",
                       owner_id=admin.id, service_id=services[1].id),
            Repository(name="core-api-gateway", full_name="acme-corp/core-api-gateway",
                       owner_id=admin.id, service_id=services[2].id),
            Repository(name="billing-api", full_name="acme-corp/billing-api",
                       owner_id=admin.id, service_id=services[3].id),
            Repository(name="fraud-service", full_name="acme-corp/fraud-service",
                       owner_id=admin.id, service_id=services[4].id),
        ]
        db.add_all(repos)
        db.flush()

        # --- Sample Incidents ---
        now = datetime.now(timezone.utc)

        inc1 = Incident(
            number=1,
            title="Payment API latency regression",
            description="p95 latency increased from 200ms to 4.2s after deployment v2.8.1",
            severity=IncidentSeverity.SEV1,
            status=IncidentStatus.CREATED,
            source=IncidentSource.MANUAL,
            service_name="payment-api",
            service_id=services[0].id,
            started_at=now - timedelta(hours=2),
            creator_id=admin.id,
        )
        db.add(inc1)

        inc2 = Incident(
            number=2,
            title="Authentication errors spike",
            description="Error rate increased to 8.7% on /api/auth endpoints",
            severity=IncidentSeverity.SEV2,
            status=IncidentStatus.INVESTIGATING,
            source=IncidentSource.ALERT,
            service_name="auth-api",
            service_id=services[1].id,
            detected_at=now - timedelta(hours=5),
            started_at=now - timedelta(hours=5),
            creator_id=admin.id,
        )
        db.add(inc2)

        inc3 = Incident(
            number=3,
            title="Billing API 500 errors",
            description="Intermittent 500 errors on invoice generation endpoint",
            severity=IncidentSeverity.SEV3,
            status=IncidentStatus.RESOLVED,
            source=IncidentSource.PROMETHEUS,
            service_name="billing-api",
            service_id=services[3].id,
            detected_at=now - timedelta(days=1),
            started_at=now - timedelta(days=1),
            resolved_at=now - timedelta(hours=20),
            creator_id=admin.id,
            confidence=Confidence.HIGH,
            root_cause_summary="Null pointer exception in invoice formatter when tax rate is zero",
        )
        db.add(inc3)

        db.flush()

        # --- Sample Investigation for inc2 ---
        inv = Investigation(
            incident_id=inc2.id,
            status=InvestigationStatus.COLLECTING_EVIDENCE,
            current_step="Collecting evidence from recent commits",
            progress_percent=35,
            llm_model="kimi-k3",
            total_tokens=12500,
            total_cost_usd=0.04,
        )
        db.add(inv)
        db.commit()

        print("Seeded: admin + 5 services + 6 repos + 3 incidents + 1 investigation")
    else:
        print("Database already seeded, skipping.")

finally:
    db.close()
