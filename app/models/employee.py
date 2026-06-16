from datetime import datetime
from ..extensions import db


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40))
    position = db.Column(db.String(80))  # detailer, washer, manager
    salary_model = db.Column(db.String(20), default="percent")  # fixed|percent|kpi
    base_salary = db.Column(db.Float, default=0)
    percent = db.Column(db.Float, default=0)
    # KPI settings
    kpi_target_visits = db.Column(db.Integer, default=0)
    kpi_bonus_per_visit = db.Column(db.Float, default=0)
    kpi_target_revenue = db.Column(db.Float, default=0)
    kpi_bonus_revenue_percent = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("employee_profile", uselist=False))
    order_assignments = db.relationship("OrderAssignment", back_populates="employee")


class Salary(db.Model):
    __tablename__ = "salaries"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)
    base = db.Column(db.Float, default=0)
    bonus = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)
    visits_count = db.Column(db.Integer, default=0)
    revenue_total = db.Column(db.Float, default=0)
    kpi_score = db.Column(db.Float, default=0)
    note = db.Column(db.String(255))
    paid = db.Column(db.Boolean, default=False)
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship("Employee")
