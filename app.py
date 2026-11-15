"""Flask application for the Community Electricity Outage Information System."""

import hmac
import os
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from datetime import timedelta, datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request, session,
    url_for,
)
from werkzeug.security import check_password_hash

from database import (
    DB_PATH, create_database, delete_announcement, delete_report,
    get_announcement, get_announcements, get_reports, save_announcement,
    save_report, update_report_status,
)

load_dotenv()

_secret_key = os.environ.get("SECRET_KEY", "").strip()
_admin_username = os.environ.get("ADMIN_USERNAME", "").strip()
_admin_password = os.environ.get("ADMIN_PASSWORD", "")
_admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()

if len(_secret_key) < 32 or _secret_key.lower().startswith("replace_with"):
    raise RuntimeError(
        "SECRET_KEY is missing or too short. Copy .env.example to .env and set a "
        "random SECRET_KEY of at least 32 characters."
    )

if (
    not _admin_username
    or _admin_username.lower().startswith("choose_a_private")
    or (
        not _admin_password_hash
        and (
            not _admin_password
            or _admin_password.lower().startswith("replace_with")
        )
    )
):
    raise RuntimeError(
        "Set ADMIN_USERNAME and either ADMIN_PASSWORD or ADMIN_PASSWORD_HASH in .env."
    )

app = Flask(__name__)

app.config.update(
    SECRET_KEY=_secret_key,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=20),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
    MAX_CONTENT_LENGTH=32 * 1024,
)

create_database()

SUPPORTED_AREAS = [
    "Gudivada",
    "Gudlavalleru",
    "Machilipatnam",
    "Bommuluru",
    "Anguluru",
]

ALL_REPORT_AREAS = SUPPORTED_AREAS + ["Other"]

REPORT_STATUSES = ["Pending", "In Progress", "Resolved"]

ANNOUNCEMENT_STATUSES = [
    "Awaiting Verification",
    "Scheduled",
    "Ongoing",
    "Completed",
    "Cancelled",
]


# Simple per-process login throttle for this educational prototype.
_login_failures = defaultdict(deque)
LOGIN_WINDOW_SECONDS = 10 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 10 * 60
_login_locked_until = {}


def csrf_token():
    token = session.get("_csrf_token")

    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token

    return token


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["supported_areas"] = SUPPORTED_AREAS


def validate_csrf():
    submitted = request.form.get("csrf_token", "")
    expected = session.get("_csrf_token", "")

    if (
        not submitted
        or not expected
        or not hmac.compare_digest(submitted, expected)
    ):
        abort(
            400,
            description=(
                "The form security token is missing or expired. "
                "Please go back, refresh the page, and try again."
            ),
        )


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash(
                "Please log in as an administrator to continue.",
                "error",
            )
            return redirect(url_for("admin_login"))

        return view(*args, **kwargs)

    return wrapped


def verify_admin_password(password):
    if _admin_password_hash:
        try:
            return check_password_hash(_admin_password_hash, password)
        except (ValueError, TypeError):
            return False

    return bool(_admin_password) and hmac.compare_digest(
        password,
        _admin_password,
    )


def login_is_locked(ip):
    now = time.time()
    locked_until = _login_locked_until.get(ip, 0)

    if now >= locked_until:
        _login_locked_until.pop(ip, None)

        failures = _login_failures[ip]

        while failures and now - failures[0] > LOGIN_WINDOW_SECONDS:
            failures.popleft()

        return False

    return True


def record_login_failure(ip):
    now = time.time()
    failures = _login_failures[ip]

    while failures and now - failures[0] > LOGIN_WINDOW_SECONDS:
        failures.popleft()

    failures.append(now)

    if len(failures) >= LOGIN_MAX_FAILURES:
        _login_locked_until[ip] = now + LOGIN_LOCK_SECONDS
        failures.clear()


@app.before_request
def enforce_admin_idle_timeout():
    if session.get("admin_logged_in"):
        now = time.time()
        last_seen = session.get("_last_seen", now)

        if now - last_seen > app.permanent_session_lifetime.total_seconds():
            session.clear()

            flash(
                "Your admin session expired due to inactivity. Please log in again.",
                "error",
            )

            if request.endpoint not in ("admin_login", "static"):
                return redirect(url_for("admin_login"))

        else:
            session["_last_seen"] = now
            session.permanent = True


# ---------------------------------------------------------
# PUBLIC PAGES
# ---------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/outages")
def outages():
    area = request.args.get("area", "").strip()

    if area not in SUPPORTED_AREAS:
        area = ""

    announcements = get_announcements(area or None)

    return render_template(
        "outages.html",
        announcements=announcements,
        selected_area=area,
    )


# ---------------------------------------------------------
# REPORT SUBMISSION WITH TRACKING CODE
# ---------------------------------------------------------

@app.route("/report", methods=["GET", "POST"])
def report():
    form_data = {
        "name": "",
        "area": "",
        "problem": "",
    }

    error = None

    if request.method == "POST":
        validate_csrf()

        form_data = {
            "name": request.form.get("name", "").strip(),
            "area": request.form.get("area", "").strip(),
            "problem": request.form.get("problem", "").strip(),
        }

        name = form_data["name"]
        area = form_data["area"]
        problem = form_data["problem"]

        if not name or not area or not problem:
            error = "Please fill in all fields."

        elif area not in ALL_REPORT_AREAS:
            error = "Please select a valid area."

        elif len(name) > 100 or len(problem) > 1000:
            error = (
                "Name must be at most 100 characters and "
                "description at most 1000 characters."
            )

        elif len(name) < 2:
            error = "Please enter a name with at least 2 characters."

        if error:
            return render_template(
                "report.html",
                error=error,
                form_data=form_data,
            ), 400

        try:
            # Save the report and receive its unique tracking code.
            tracking_code = save_report(name, area, problem)

            # Temporarily store the code for the success page.
            session["last_report_tracking_code"] = tracking_code

        except sqlite3.Error:
            app.logger.exception("Could not save a CEOIS report")

            return render_template(
                "report.html",
                error="We could not save your report. Please try again.",
                form_data=form_data,
            ), 500

        return redirect(url_for("report_success"))

    return render_template(
        "report.html",
        form_data=form_data,
    )


@app.route("/report-success")
def report_success():
    # Get the tracking code and remove it from the session.
    tracking_code = session.pop(
        "last_report_tracking_code",
        None,
    )

    return render_template(
        "report_success.html",
        tracking_code=tracking_code,
    )


# ---------------------------------------------------------
# TRACK REPORT
# ---------------------------------------------------------

@app.route("/track-report", methods=["GET", "POST"])
def track_report():
    report_data = None
    error = None
    tracking_code = ""

    if request.method == "POST":
        validate_csrf()

        tracking_code = request.form.get(
            "tracking_code",
            "",
        ).strip().upper()

        # Validate the tracking-code format.
        # Example: CEOIS-A3F82B91
        if (
            len(tracking_code) != 14
            or not tracking_code.startswith("CEOIS-")
            or not all(
                character in "0123456789ABCDEF"
                for character in tracking_code[6:]
            )
        ):
            error = "Please enter a valid tracking code."

        else:
            try:
                # Search using the tracking code.
                # Only safe, necessary details are retrieved.
                with sqlite3.connect(DB_PATH) as connection:
                    connection.row_factory = sqlite3.Row

                    report_data = connection.execute(
                        """
                        SELECT tracking_code, area, report_date, status
                        FROM reports
                        WHERE tracking_code = ?
                        COLLATE NOCASE
                        """,
                        (tracking_code,),
                    ).fetchone()

            except sqlite3.Error:
                app.logger.exception(
                    "Could not retrieve report tracking information"
                )
                error = (
                    "Report tracking is temporarily unavailable. "
                    "Please try again."
                )

            if not error and report_data is None:
                error = (
                    "No report was found with this tracking code. "
                    "Please check the code and try again."
                )

    return render_template(
        "track_report.html",
        report_data=report_data,
        error=error,
        tracking_code=tracking_code,
    )


# ---------------------------------------------------------
# COMMUNITY REPORT SUMMARY API
# ---------------------------------------------------------

@app.route("/api/status/<area>")
def api_status(area):
    """Return aggregate community-report counts, never personal report details."""

    if area not in SUPPORTED_AREAS:
        return jsonify({"error": "Unknown area"}), 404

    try:
        reports = get_reports(area=area)

    except sqlite3.Error:
        app.logger.exception("Could not read report summary")

        return jsonify({
            "error": "Status summary is temporarily unavailable"
        }), 503

    counts = {
        status: 0
        for status in REPORT_STATUSES
    }

    for row in reports:
        if row["status"] in counts:
            counts[row["status"]] += 1

    return jsonify({
        "area": area,
        "total": len(reports),
        "summary": counts if reports else None,
        "information_type": "community_report_summary",
        "live_electricity_status": "unverified",
    })


# ---------------------------------------------------------
# ADMIN LOGIN
# ---------------------------------------------------------

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin"))

    error = None
    username_value = ""

    if request.method == "POST":
        validate_csrf()

        ip = request.remote_addr or "unknown"

        username_value = request.form.get(
            "username",
            "",
        ).strip()

        password = request.form.get("password", "")

        if login_is_locked(ip):
            error = (
                "Too many unsuccessful attempts. "
                "Please wait 10 minutes before trying again."
            )

        elif (
            hmac.compare_digest(username_value, _admin_username)
            and verify_admin_password(password)
        ):
            _login_failures.pop(ip, None)
            _login_locked_until.pop(ip, None)

            session.clear()
            session["admin_logged_in"] = True
            session["_last_seen"] = time.time()
            session.permanent = True

            csrf_token()

            return redirect(url_for("admin"))

        else:
            record_login_failure(ip)
            error = "Invalid username or password."

    return render_template(
        "admin_login.html",
        error=error,
        username_value=username_value,
    )


# ---------------------------------------------------------
# ADMIN DASHBOARD
# ---------------------------------------------------------

@app.route("/admin")
@admin_required
def admin():
    area = request.args.get("area", "").strip()
    status = request.args.get("status", "").strip()

    if area not in ALL_REPORT_AREAS:
        area = ""

    if status not in REPORT_STATUSES:
        status = ""

    try:
        reports = get_reports(
            area or None,
            status or None,
        )

    except sqlite3.Error:
        app.logger.exception("Could not load admin reports")

        flash(
            "Reports could not be loaded. Please try again.",
            "error",
        )

        reports = []

    return render_template(
        "admin.html",
        reports=reports,
        selected_area=area,
        selected_status=status,
        report_statuses=REPORT_STATUSES,
        all_report_areas=ALL_REPORT_AREAS,
    )


@app.route("/update-status/<int:report_id>", methods=["POST"])
@admin_required
def update_status(report_id):
    validate_csrf()

    new_status = request.form.get("status", "")

    if new_status not in REPORT_STATUSES:
        flash(
            "Invalid report status selected.",
            "error",
        )
        return redirect(url_for("admin"))

    try:
        updated = update_report_status(
            report_id,
            new_status,
        )

    except sqlite3.Error:
        app.logger.exception("Could not update report status")

        flash(
            "The report status could not be updated.",
            "error",
        )

        return redirect(url_for("admin"))

    flash(
        "Report status updated."
        if updated
        else "Report not found; no changes were made.",
        "success" if updated else "error",
    )

    return redirect(url_for("admin"))


@app.route("/delete-report/<int:report_id>", methods=["POST"])
@admin_required
def remove_report(report_id):
    validate_csrf()

    try:
        deleted = delete_report(report_id)

    except sqlite3.Error:
        app.logger.exception("Could not delete report")

        flash(
            "The report could not be deleted.",
            "error",
        )

        return redirect(url_for("admin"))

    flash(
        "Report deleted."
        if deleted
        else "Report not found; nothing was deleted.",
        "success" if deleted else "error",
    )

    return redirect(url_for("admin"))


# ---------------------------------------------------------
# OUTAGE ANNOUNCEMENT VALIDATION
# ---------------------------------------------------------

def validate_announcement_form(form):
    values = {
        "area": form.get("area", "").strip(),
        "outage_date": form.get("outage_date", "").strip(),
        "start_time": form.get("start_time", "").strip(),
        "restoration_time": form.get("restoration_time", "").strip(),
        "reason": form.get("reason", "").strip(),
        "status": form.get(
            "status",
            "Awaiting Verification",
        ).strip(),
    }

    if values["area"] not in SUPPORTED_AREAS:
        return values, "Please select a valid area."

    try:
        datetime.strptime(
            values["outage_date"],
            "%Y-%m-%d",
        )

        datetime.strptime(
            values["start_time"],
            "%H:%M",
        )

        datetime.strptime(
            values["restoration_time"],
            "%H:%M",
        )

    except ValueError:
        return values, "Enter a valid date and time."

    if not values["reason"]:
        return values, (
            "Please enter the reason or write 'Awaiting verification'."
        )

    if len(values["reason"]) > 500:
        return values, "Reason must be 500 characters or fewer."

    if values["status"] not in ANNOUNCEMENT_STATUSES:
        return values, "Please select a valid announcement status."

    return values, None


# ---------------------------------------------------------
# ADMIN OUTAGE ANNOUNCEMENTS
# ---------------------------------------------------------

@app.route("/admin/outages")
@admin_required
def admin_outages():
    return render_template(
        "admin_outages.html",
        announcements=get_announcements(),
        announcement_statuses=ANNOUNCEMENT_STATUSES,
        form_data=None,
        editing_id=None,
        error=None,
    )


@app.route("/admin/outages/add", methods=["GET", "POST"])
@admin_required
def add_announcement():
    if request.method == "POST":
        validate_csrf()

        values, error = validate_announcement_form(
            request.form
        )

        if error:
            return render_template(
                "admin_outages.html",
                announcements=get_announcements(),
                announcement_statuses=ANNOUNCEMENT_STATUSES,
                form_data=values,
                editing_id=None,
                error=error,
            ), 400

        try:
            save_announcement(**values)

        except sqlite3.Error:
            app.logger.exception(
                "Could not add outage announcement"
            )

            return render_template(
                "admin_outages.html",
                announcements=get_announcements(),
                announcement_statuses=ANNOUNCEMENT_STATUSES,
                form_data=values,
                editing_id=None,
                error=(
                    "Announcement could not be saved. "
                    "Please try again."
                ),
            ), 500

        flash(
            "Outage announcement added.",
            "success",
        )

        return redirect(url_for("admin_outages"))

    return render_template(
        "admin_outages.html",
        announcements=get_announcements(),
        announcement_statuses=ANNOUNCEMENT_STATUSES,
        form_data=None,
        editing_id=None,
        error=None,
    )


@app.route(
    "/admin/outages/<int:announcement_id>/edit",
    methods=["GET", "POST"],
)
@admin_required
def edit_announcement(announcement_id):
    announcement = get_announcement(announcement_id)

    if not announcement:
        flash(
            "Announcement not found.",
            "error",
        )
        return redirect(url_for("admin_outages"))

    if request.method == "POST":
        validate_csrf()

        values, error = validate_announcement_form(
            request.form
        )

        if error:
            return render_template(
                "admin_outages.html",
                announcements=get_announcements(),
                announcement_statuses=ANNOUNCEMENT_STATUSES,
                form_data=values,
                editing_id=announcement_id,
                error=error,
            ), 400

        try:
            updated = save_announcement(
                **values,
                announcement_id=announcement_id,
            )

        except sqlite3.Error:
            app.logger.exception(
                "Could not edit outage announcement"
            )
            updated = False

        if not updated:
            flash(
                "Announcement could not be updated.",
                "error",
            )

        else:
            flash(
                "Outage announcement updated.",
                "success",
            )

        return redirect(url_for("admin_outages"))

    form_data = {
        key: announcement[key]
        for key in (
            "area",
            "outage_date",
            "start_time",
            "restoration_time",
            "reason",
            "status",
        )
    }

    return render_template(
        "admin_outages.html",
        announcements=get_announcements(),
        announcement_statuses=ANNOUNCEMENT_STATUSES,
        form_data=form_data,
        editing_id=announcement_id,
        error=None,
    )


@app.route(
    "/admin/outages/<int:announcement_id>/delete",
    methods=["POST"],
)
@admin_required
def remove_announcement(announcement_id):
    validate_csrf()

    try:
        deleted = delete_announcement(announcement_id)

    except sqlite3.Error:
        app.logger.exception(
            "Could not delete outage announcement"
        )
        deleted = False

    flash(
        "Announcement deleted."
        if deleted
        else "Announcement not found or could not be deleted.",
        "success" if deleted else "error",
    )

    return redirect(url_for("admin_outages"))


# ---------------------------------------------------------
# ADMIN LOGOUT
# ---------------------------------------------------------

@app.route("/admin-logout", methods=["POST"])
@admin_required
def admin_logout():
    validate_csrf()

    session.clear()

    flash(
        "You have been logged out.",
        "success",
    )

    return redirect(url_for("admin_login"))


# ---------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------

@app.errorhandler(400)
def bad_request(error):
    return render_template(
        "error.html",
        code=400,
        message=getattr(
            error,
            "description",
            "The request could not be processed.",
        ),
    ), 400


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "error.html",
        code=404,
        message="The page or record you requested was not found.",
    ), 404


@app.errorhandler(413)
def request_too_large(error):
    return render_template(
        "error.html",
        code=413,
        message="The submitted form is too large.",
    ), 413


# ---------------------------------------------------------
# RUN APPLICATION
# ---------------------------------------------------------

if __name__ == "__main__":
    debug_mode = (
        os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    )

    app.run(debug=debug_mode)