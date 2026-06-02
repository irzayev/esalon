"""Flask application factory."""
from __future__ import annotations
import os
from flask import Flask, render_template, redirect, url_for, request, abort, jsonify
from flask_login import current_user
from sqlalchemy import text

from .config import Config
from .extensions import db, login_manager, csrf, migrate, limiter


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)
    if hasattr(config_class, "validate"):
        config_class.validate()

    # Trust the reverse proxy (nginx) headers so url_for(_external=True) builds
    # https URLs. Without this the Azericard BACKREF is emitted as http and the
    # bank never delivers the payment callback (payments stay pending).
    hops = app.config.get("PROXY_FIX_HOPS", 0)
    if hops:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_port=hops
        )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    from .utils.url_converters import register_url_converters
    register_url_converters(app)

    from .models import user  # noqa: F401 — register models
    from . import models as _models  # noqa: F401 — register all tables for create_all
    from .models.user import User

    @login_manager.user_loader
    def load_user(uid: str):
        return db.session.get(User, int(uid))

    # Blueprints
    from .blueprints.auth.routes import bp as auth_bp
    from .blueprints.admin.routes import bp as admin_bp
    from .blueprints.crm.routes import bp as crm_bp
    from .blueprints.orders.routes import bp as orders_bp
    from .blueprints.services.routes import bp as services_bp
    from .blueprints.inventory.routes import bp as inventory_bp
    from .blueprints.finance.routes import bp as finance_bp
    from .blueprints.reports.routes import bp as reports_bp
    from .blueprints.employees.routes import bp as employees_bp
    from .blueprints.dashboard.routes import bp as dashboard_bp
    from .blueprints.worker.routes import bp as worker_bp
    from .blueprints.payments.routes import bp as payments_bp
    from .blueprints.client_portal.routes import bp as client_portal_bp
    from .blueprints.schedule.routes import bp as schedule_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(payments_bp, url_prefix="/payments")
    app.register_blueprint(client_portal_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(crm_bp, url_prefix="/crm")
    app.register_blueprint(orders_bp, url_prefix="/orders")
    app.register_blueprint(services_bp, url_prefix="/services")
    app.register_blueprint(inventory_bp, url_prefix="/inventory")
    app.register_blueprint(finance_bp, url_prefix="/finance")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(employees_bp, url_prefix="/employees")
    app.register_blueprint(worker_bp)
    app.register_blueprint(schedule_bp)

    # Health
    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    @app.route("/favicon.ico")
    def favicon():
        from .models.settings import Settings

        settings = Settings.get()
        if settings.company_logo and settings.logo_path():
            return redirect(settings.logo_url())
        abort(404)

    @app.route("/cron/wa-reminders")
    def cron_wa_reminders():
        """HTTP endpoint для планировщика (cron, Task Scheduler)."""
        secret = app.config.get("CRON_SECRET") or ""
        token = request.args.get("token") or request.headers.get("X-Cron-Token") or ""
        if not secret or token != secret:
            abort(403)
        from .services.whatsapp_messages import send_reminders

        dry_run = request.args.get("dry_run") in ("1", "true", "yes")
        return jsonify(send_reminders(dry_run=dry_run))

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            from .utils.auth_redirect import home_endpoint_for
            return redirect(url_for(home_endpoint_for(current_user)))
        return redirect(url_for("auth.login"))

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if app.config.get("IS_PRODUCTION"):
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resp

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def too_many_requests(e):
        return render_template("errors/429.html"), 429

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    # Bootstrap DB + admin + default settings (serialized for multi-worker gunicorn)
    with app.app_context():
        from .utils.db_init import db_bootstrap_lock

        with db_bootstrap_lock(app):
            db.create_all()
            _ensure_settings_columns()
            _ensure_employee_salary_columns()
            _ensure_order_inventory_columns()
            _ensure_order_material_plan_columns()
            _ensure_client_car_columns()
            _ensure_service_body_type_columns()
            _ensure_wa_columns()
            _ensure_azericard_columns()
            _ensure_scheduling_columns()
            _ensure_order_updated_at_column()
            _ensure_order_work_time_columns()
            _ensure_order_promo_columns()
            _ensure_promo_codes_table()
            _ensure_user_columns()
            _backfill_order_assignments()
            _bootstrap(app)

    from .cli import register_cli
    register_cli(app)

    # Template helpers
    from .utils.template_filters import register_filters
    register_filters(app)

    from .utils.i18n import init_i18n
    init_i18n(app)

    @app.before_request
    def _enforce_password_change():
        if not current_user.is_authenticated:
            return None
        if not getattr(current_user, "must_change_password", False):
            return None
        allowed = {"auth.profile", "auth.logout", "auth.switch_locale", "static"}
        if request.endpoint in allowed:
            return None
        from flask import flash
        flash("Смените пароль по умолчанию перед продолжением.", "error")
        return redirect(url_for("auth.profile"))

    @app.context_processor
    def inject_branch_ui():
        from flask import request
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {}
        from .utils.branches import branch_filter_context
        return branch_filter_context(request, current_user)

    return app


def _bootstrap(app: Flask) -> None:
    """Create default admin and settings if not exist."""
    from .models.user import User, Role
    from .models.settings import Settings
    from werkzeug.security import generate_password_hash

    if not User.query.filter_by(email=app.config["ADMIN_EMAIL"]).first():
        from .config import DEFAULT_ADMIN_PASSWORD

        admin = User(
            email=app.config["ADMIN_EMAIL"],
            name="Administrator",
            password_hash=generate_password_hash(app.config["ADMIN_PASSWORD"]),
            role=Role.ADMIN,
            is_active=True,
            # Force a password change if the admin was created with the
            # development default (only possible outside production).
            must_change_password=app.config["ADMIN_PASSWORD"] == DEFAULT_ADMIN_PASSWORD,
        )
        db.session.add(admin)

    if not Settings.query.first():
        db.session.add(Settings())

    db.session.commit()


def _ensure_settings_columns() -> None:
    """Lightweight schema patch for newly added settings columns.

    We keep this for SQLite deployments without migrations where table
    already exists from previous runs.
    """
    expected = {
        "receipt_template": "TEXT DEFAULT ''",
        "receipt_cashier_name": "TEXT DEFAULT ''",
        "receipt_footer_note": "TEXT DEFAULT ''",
        "company_website": "TEXT DEFAULT ''",
        "wa_template_ready": "TEXT DEFAULT ''",
        "wa_template_booking": "TEXT DEFAULT ''",
        "wa_template_reminder": "TEXT DEFAULT ''",
        "company_tagline": "TEXT DEFAULT ''",
        "company_waze": "TEXT DEFAULT ''",
    }
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(settings)")).fetchall()
        existing = {row[1] for row in cols}
        for col, ddl in expected.items():
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE settings ADD COLUMN {col} {ddl}"))
                except Exception:
                    # Safe ignore for race/restart cases where another process added it.
                    pass


def _ensure_employee_salary_columns() -> None:
    """Add payroll/KPI columns for existing SQLite tables."""
    employees_expected = {
        "kpi_target_cars": "INTEGER DEFAULT 0",
        "kpi_bonus_per_car": "FLOAT DEFAULT 0",
        "kpi_target_revenue": "FLOAT DEFAULT 0",
        "kpi_bonus_revenue_percent": "FLOAT DEFAULT 0",
    }
    salaries_expected = {
        "cars_count": "INTEGER DEFAULT 0",
        "revenue_total": "FLOAT DEFAULT 0",
        "kpi_score": "FLOAT DEFAULT 0",
        "note": "TEXT",
        "paid_at": "DATETIME",
    }
    with db.engine.begin() as conn:
        for table, expected in (("employees", employees_expected), ("salaries", salaries_expected)):
            cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {row[1] for row in cols}
            for col, ddl in expected.items():
                if col not in existing:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    except Exception:
                        pass


def _ensure_order_material_plan_columns() -> None:
    expected = {"is_manual": "INTEGER DEFAULT 0"}
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(order_material_plans)")).fetchall()
        existing = {row[1] for row in cols}
        for col, ddl in expected.items():
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE order_material_plans ADD COLUMN {col} {ddl}"))
                except Exception:
                    pass


def _ensure_order_inventory_columns() -> None:
    orders_expected = {"inventory_consumed_at": "DATETIME"}
    items_expected = {"package_id": "INTEGER"}
    with db.engine.begin() as conn:
        for table, expected in (("orders", orders_expected), ("order_items", items_expected)):
            cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {row[1] for row in cols}
            for col, ddl in expected.items():
                if col not in existing:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    except Exception:
                        pass


def _ensure_wa_columns() -> None:
    clients_expected = {"wa_last_reminder_at": "DATETIME"}
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(clients)")).fetchall()
        existing = {row[1] for row in cols}
        for col, ddl in clients_expected.items():
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE clients ADD COLUMN {col} {ddl}"))
                except Exception:
                    pass


def _backfill_order_assignments() -> None:
    """Copy legacy assigned_to_id into order_assignments for existing orders."""
    from .models.order import Order
    from .models.order_assignment import OrderAssignment

    try:
        assigned_orders = Order.query.filter(Order.assigned_to_id.isnot(None)).all()
    except Exception:
        return
    for order in assigned_orders:
        if order.assignments:
            continue
        db.session.add(
            OrderAssignment(order_id=order.id, employee_id=order.assigned_to_id)
        )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _ensure_azericard_columns() -> None:
    settings_expected = {
        "azericard_email": "TEXT DEFAULT ''",
        "azericard_merch_gmt": "TEXT DEFAULT '+4'",
        "azericard_private_key_pem": "TEXT DEFAULT ''",
        "azericard_public_key_pem": "TEXT DEFAULT ''",
        "wa_template_payment": "TEXT DEFAULT ''",
        "evolution_send_on_status_change": "BOOLEAN DEFAULT 0",
        "wa_template_status_change": "TEXT DEFAULT ''",
        "azericard_client_portal_enabled": "BOOLEAN DEFAULT 0",
    }
    intents_expected = {"pay_token": "TEXT", "audit_channel": "TEXT DEFAULT ''"}
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(settings)")).fetchall()
        existing = {row[1] for row in cols}
        for col, ddl in settings_expected.items():
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE settings ADD COLUMN {col} {ddl}"))
                except Exception:
                    pass
        try:
            intent_cols = conn.execute(text("PRAGMA table_info(azericard_payment_intents)")).fetchall()
        except Exception:
            intent_cols = []
        if intent_cols:
            intent_existing = {row[1] for row in intent_cols}
            for col, ddl in intents_expected.items():
                if col not in intent_existing:
                    try:
                        conn.execute(
                            text(f"ALTER TABLE azericard_payment_intents ADD COLUMN {col} {ddl}")
                        )
                    except Exception:
                        pass


def _ensure_scheduling_columns() -> None:
    """Bays tables + order/service scheduling columns for SQLite without migrations."""
    orders_expected = {
        "bay_id": "INTEGER",
        "scheduled_end_at": "DATETIME",
    }
    services_expected = {"required_bay_type": "TEXT"}
    with db.engine.begin() as conn:
        for table, expected in (("orders", orders_expected), ("services", services_expected)):
            cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {row[1] for row in cols}
            for col, ddl in expected.items():
                if col not in existing:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    except Exception:
                        pass


def _ensure_order_updated_at_column() -> None:
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(orders)")).fetchall()
        existing = {row[1] for row in cols}
        if "updated_at" not in existing:
            try:
                conn.execute(text("ALTER TABLE orders ADD COLUMN updated_at DATETIME"))
                conn.execute(
                    text(
                        "UPDATE orders SET updated_at = COALESCE("
                        "completed_at, started_at, inventory_consumed_at, created_at)"
                    )
                )
            except Exception:
                pass


def _ensure_order_work_time_columns() -> None:
    expected = {
        "in_progress_minutes": "INTEGER DEFAULT 0",
        "in_progress_since": "DATETIME",
    }
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(orders)")).fetchall()
        existing = {row[1] for row in cols}
        for col, ddl in expected.items():
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col} {ddl}"))
                except Exception:
                    pass
        try:
            conn.execute(
                text(
                    "UPDATE orders SET in_progress_since = started_at "
                    "WHERE status = 'in_progress' AND started_at IS NOT NULL "
                    "AND in_progress_since IS NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE orders SET in_progress_minutes = CAST("
                    "(julianday(completed_at) - julianday(started_at)) * 1440 AS INTEGER) "
                    "WHERE status IN ('done', 'delivered') "
                    "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
                    "AND COALESCE(in_progress_minutes, 0) = 0"
                )
            )
        except Exception:
            pass


def _ensure_order_promo_columns() -> None:
    expected = {
        "promo_code_id": "INTEGER",
        "promo_code_text": "TEXT",
        "promo_use_counted": "BOOLEAN DEFAULT 0",
    }
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(orders)")).fetchall()
        existing = {row[1] for row in cols}
        for col, ddl in expected.items():
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col} {ddl}"))
                except Exception:
                    pass


def _ensure_promo_codes_table() -> None:
    """Create promo_codes table and migrate columns on existing SQLite DBs."""
    from sqlalchemy import inspect

    from .models.promo_code import PromoCode

    insp = inspect(db.engine)
    if not insp.has_table("promo_codes"):
        PromoCode.__table__.create(db.engine, checkfirst=True)
        return

    expected = {
        "valid_from": "DATETIME",
    }
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(promo_codes)")).fetchall()
        existing = {row[1] for row in cols}
        for col, ddl in expected.items():
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE promo_codes ADD COLUMN {col} {ddl}"))
                except Exception:
                    pass


def _ensure_user_columns() -> None:
    users_expected = {
        "must_change_password": "BOOLEAN DEFAULT 0",
        "last_login_at": "DATETIME",
    }
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(users)")).fetchall()
        existing = {row[1] for row in cols}
        for col, ddl in users_expected.items():
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
                except Exception:
                    pass


def _ensure_client_car_columns() -> None:
    cars_expected = {"body_type": "TEXT DEFAULT 'sedan'"}
    with db.engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(cars)")).fetchall()
        existing = {row[1] for row in cols}
        for col, ddl in cars_expected.items():
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE cars ADD COLUMN {col} {ddl}"))
                except Exception:
                    pass
        try:
            conn.execute(
                text(
                    "UPDATE cars SET body_type = 'sedan' "
                    "WHERE body_type IS NULL OR body_type = ''"
                )
            )
            conn.execute(
                text("UPDATE cars SET plate = REPLACE(plate, '-', '') WHERE plate LIKE '%-%'")
            )
        except Exception:
            pass


def _ensure_service_body_type_columns() -> None:
    expected = {
        "services": {
            "body_type": "TEXT DEFAULT 'sedan'",
            "body_types": "TEXT DEFAULT 'sedan'",
        },
        "service_packages": {
            "body_type": "TEXT DEFAULT 'sedan'",
            "body_types": "TEXT DEFAULT 'sedan'",
        },
    }
    with db.engine.begin() as conn:
        for table, columns in expected.items():
            cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {row[1] for row in cols}
            for col, ddl in columns.items():
                if col not in existing:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    except Exception:
                        pass
            try:
                conn.execute(
                    text(
                        f"UPDATE {table} SET body_type = 'sedan' "
                        "WHERE body_type IS NULL OR body_type = ''"
                    )
                )
                conn.execute(
                    text(
                        f"UPDATE {table} SET body_types = body_type "
                        f"WHERE (body_types IS NULL OR body_types = '') "
                        f"AND body_type IS NOT NULL AND body_type != ''"
                    )
                )
                conn.execute(
                    text(
                        f"UPDATE {table} SET body_types = 'sedan' "
                        "WHERE body_types IS NULL OR body_types = ''"
                    )
                )
            except Exception:
                pass
