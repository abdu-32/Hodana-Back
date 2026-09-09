"""
hackathons -- exports

Generates production-ready exports (Excel .xlsx, CSV .csv, PDF .pdf) for:
- Participants / Registrations
- Teams & Rosters
- Project Submissions
- Judging Results & Scores
- Prizes & Winners
- Analytics & Demographics
- Complete Hackathon Multi-Sheet Report
"""

import csv
import io
from datetime import datetime
from decimal import Decimal
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


# ==============================================================================
# EXCEL STYLING CONSTANTS
# ==============================================================================

HEADER_FILL = PatternFill(start_color="0F6B5C", end_color="0F6B5C", fill_type="solid")
HEADER_FONT = Font(name="Arial", size=11, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="Arial", size=14, bold=True, color="0F6B5C")
SUBTITLE_FONT = Font(name="Arial", size=10, italic=True, color="57685F")
BOLD_FONT = Font(name="Arial", size=10, bold=True, color="122622")
REGULAR_FONT = Font(name="Arial", size=10, color="122622")
MUTED_FONT = Font(name="Arial", size=9, color="57685F")

THIN_BORDER_SIDE = Side(border_style="thin", color="D6E7E1")
TABLE_BORDER = Border(
    left=THIN_BORDER_SIDE,
    right=THIN_BORDER_SIDE,
    top=THIN_BORDER_SIDE,
    bottom=THIN_BORDER_SIDE,
)

ZEBRA_FILL = PatternFill(start_color="F8FAF9", end_color="F8FAF9", fill_type="solid")


def _auto_adjust_columns(ws, min_width=12, max_width=45):
    """Automatically scales column widths to fit content nicely."""
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val = str(cell.value or "")
            if "\n" in val:
                val = max(val.split("\n"), key=len)
            max_len = max(max_len, len(val))
        ws.column_dimensions[col_letter].width = max(min_width, min(max_len + 3, max_width))


def _style_header_row(ws, row_idx=1):
    """Applies high-end brand header styling."""
    for cell in ws[row_idx]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = TABLE_BORDER
    ws.row_dimensions[row_idx].height = 26


# ==============================================================================
# DATA COLLECTORS & TRANSFORMERS
# ==============================================================================

def get_participants_data(hackathons, filters=None):
    """Extracts participant registration rows across the target hackathon(s)."""
    filters = filters or {}
    search = str(filters.get("search") or "").lower().strip()
    status_filter = str(filters.get("status") or "").upper().strip()
    role_filter = str(filters.get("role") or "").lower().strip()
    city_filter = str(filters.get("city") or "").lower().strip()

    rows = []
    for h in hackathons:
        registrations = h.registrations.select_related("user").all().order_by("-registered_at")
        for reg in registrations:
            user = reg.user
            custom = reg.custom_answers or {}
            personal = custom.get("personalInfo", {})

            full_name = personal.get("fullName") or getattr(user, "full_name", "") or f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() or "Anonymous"
            email = personal.get("email") or getattr(user, "email", "")
            phone = personal.get("phone") or getattr(user, "phone_number", "") or ""
            city = personal.get("city") or getattr(user, "city", "") or ""
            country = getattr(user, "country", "") or ""
            org = personal.get("organization") or getattr(user, "organization", "") or getattr(user, "university", "") or ""
            role = personal.get("role") or getattr(user, "profession", "") or getattr(user, "professional_title", "") or "Participant"
            experience = getattr(user, "experience_level", "") or "Intermediate"
            skills_str = ", ".join(getattr(user, "skills", []))
            linkedin = getattr(user, "linkedin_url", "")
            github = getattr(user, "github_url", "")
            website = getattr(user, "website_url", "") or getattr(user, "portfolio_url", "")
            status = "WITHDRAWN" if reg.withdrawn_at else "APPROVED" if reg.eligibility_confirmed else "PENDING"
            
            # Team lookup
            team_memberships = reg.user.team_memberships.filter(team__hackathon=h)
            team_name = team_memberships.first().team.team_name if team_memberships.exists() else "No Team"

            discovery = custom.get("discovery", {})
            discovery_source = discovery.get("source") or "Direct / Platform"
            if discovery.get("platform"):
                discovery_source += f" ({discovery.get('platform')})"
            elif discovery.get("otherText"):
                discovery_source += f" ({discovery.get('otherText')})"

            # Apply filters
            if search and not (
                search in full_name.lower()
                or search in email.lower()
                or search in city.lower()
                or search in org.lower()
            ):
                continue
            if status_filter and status_filter != "ALL" and status != status_filter:
                continue
            if role_filter and role_filter != "all" and role_filter not in role.lower():
                continue
            if city_filter and city_filter != "all" and city_filter not in city.lower():
                continue

            rows.append({
                "participant_id": str(user.id),
                "registration_id": str(reg.id),
                "hackathon_id": str(h.id),
                "hackathon_title": h.title,
                "full_name": full_name,
                "email": email,
                "phone": phone,
                "country": country,
                "city": city,
                "organization": org,
                "role": role,
                "experience": experience,
                "skills": skills_str,
                "linkedin": linkedin,
                "github": github,
                "website": website,
                "team_name": team_name,
                "registered_at": reg.registered_at.strftime("%Y-%m-%d %H:%M:%S") if reg.registered_at else "",
                "status": status,
                "eligibility_confirmed": "Yes" if reg.eligibility_confirmed else "No",
                "referral_source": discovery_source,
            })
    return rows


def get_teams_data(hackathons, filters=None):
    """Extracts teams and member rosters."""
    rows = []
    for h in hackathons:
        teams = h.teams.select_related("leader_user").prefetch_related("members__user").all().order_by("-created_at")
        for team in teams:
            leader = team.leader_user
            leader_name = getattr(leader, "full_name", "") or f"{getattr(leader, 'first_name', '')} {getattr(leader, 'last_name', '')}".strip() or getattr(leader, "email", "Leader")
            members = team.members.select_related("user").all()
            member_names = []
            member_emails = []
            for m in members:
                m_user = m.user
                name = getattr(m_user, "full_name", "") or f"{getattr(m_user, 'first_name', '')} {getattr(m_user, 'last_name', '')}".strip() or getattr(m_user, "email", "")
                member_names.append(name)
                member_emails.append(getattr(m_user, "email", ""))

            submission = getattr(team, "submission", None)
            submission_title = submission.title if submission else "No Submission"
            status = "Submitted" if (submission and submission.submitted_at) else "Forming" if team.open_to_members else "Complete"

            rows.append({
                "team_id": str(team.id),
                "hackathon_id": str(h.id),
                "hackathon_title": h.title,
                "team_name": team.team_name,
                "leader_name": leader_name,
                "leader_email": getattr(leader, "email", ""),
                "team_size": len(members),
                "max_size": team.max_size,
                "member_names": ", ".join(member_names),
                "member_emails": ", ".join(member_emails),
                "submission_title": submission_title,
                "open_to_members": "Yes" if team.open_to_members else "No",
                "status": status,
                "created_at": team.created_at.strftime("%Y-%m-%d %H:%M:%S") if team.created_at else "",
            })
    return rows


def get_submissions_data(hackathons, filters=None):
    """Extracts project submissions."""
    rows = []
    for h in hackathons:
        submissions = h.submissions.select_related("team__leader_user").all().order_by("-submitted_at")
        for sub in submissions:
            team = sub.team
            leader = team.leader_user if team else None
            leader_name = getattr(leader, "full_name", "") or getattr(leader, "email", "N/A") if leader else "N/A"
            techs = ", ".join(sub.technologies) if sub.technologies else ""

            status = "Disqualified" if sub.eligibility_status == "disqualified" else "Eligible" if sub.eligibility_status == "eligible" else "Submitted" if sub.submitted_at else "Draft"

            rows.append({
                "submission_id": str(sub.id),
                "hackathon_id": str(h.id),
                "hackathon_title": h.title,
                "project_title": sub.title or "Untitled Project",
                "team_name": team.team_name if team else "Independent",
                "leader_name": leader_name,
                "tagline": sub.tagline or "",
                "description": sub.description or "",
                "technologies": techs,
                "repo_url": sub.repo_link or "",
                "demo_url": sub.demo_link or "",
                "video_url": sub.video_link or "",
                "status": status,
                "submitted_at": sub.submitted_at.strftime("%Y-%m-%d %H:%M:%S") if sub.submitted_at else "Not Finalized",
            })
    return rows


def get_judging_data(hackathons, filters=None):
    """Extracts judging evaluations and scorecards."""
    rows = []
    for h in hackathons:
        rounds = h.judging_rounds.prefetch_related("criteria", "assignments__submission", "assignments__judge_user").all()
        for r in rounds:
            assignments = r.assignments.select_related("submission__team", "judge_user").all()
            for assign in assignments:
                sub = assign.submission
                judge = assign.judge_user
                judge_name = getattr(judge, "full_name", "") or f"{getattr(judge, 'first_name', '')} {getattr(judge, 'last_name', '')}".strip() or getattr(judge, "email", "Judge")

                scores = sub.scores.filter(judge_user=judge).select_related("criterion")
                if scores.exists():
                    total_score = sum(s.score_value for s in scores)
                    avg_score = total_score / len(scores) if scores else 0
                    comments = " | ".join([s.comment for s in scores if s.comment])
                    status = "Evaluated"
                else:
                    total_score = 0
                    avg_score = 0
                    comments = ""
                    status = "Pending Evaluation"

                rows.append({
                    "assignment_id": str(assign.id),
                    "hackathon_id": str(h.id),
                    "hackathon_title": h.title,
                    "round_status": r.status,
                    "project_title": sub.title or "Untitled",
                    "team_name": sub.team.team_name if sub.team else "N/A",
                    "judge_name": judge_name,
                    "judge_email": getattr(judge, "email", ""),
                    "total_score": round(total_score, 2),
                    "average_score": round(avg_score, 2),
                    "status": status,
                    "comments": comments,
                    "assigned_at": assign.assigned_at.strftime("%Y-%m-%d %H:%M:%S") if assign.assigned_at else "",
                })
    return rows


def get_prizes_data(hackathons):
    """Extracts prize tier allocations and winners."""
    rows = []
    for h in hackathons:
        dist = h.prize_distribution or {}
        currency = dist.get("currency", "USD")
        total_budget = h.total_prize_budget or 0

        # Tiers
        prizes = [
            {"position": "1st Place", "title": "Grand Champion", "amount": dist.get("firstPlaceAmount", 0)},
            {"position": "2nd Place", "title": "Runner Up", "amount": dist.get("secondPlaceAmount", 0)},
            {"position": "3rd Place", "title": "Third Place Finalist", "amount": dist.get("thirdPlaceAmount", 0)},
        ]

        # Top submissions by average judging score
        top_submissions = (
            h.submissions.filter(eligibility_status__in=["eligible", "pending"])
            .select_related("team")
            .all()
        )
        ranked_list = []
        for s in top_submissions:
            scores = s.scores.all()
            if scores.exists():
                avg = sum(sc.score_value for sc in scores) / len(scores)
                ranked_list.append((avg, s))
        ranked_list.sort(key=lambda x: x[0], reverse=True)

        for idx, p in enumerate(prizes):
            winner_team = "TBD"
            winner_project = "TBD"
            if idx < len(ranked_list):
                winner_score, winning_sub = ranked_list[idx]
                winner_team = winning_sub.team.team_name if winning_sub.team else "Independent"
                winner_project = winning_sub.title or "Untitled"

            rows.append({
                "hackathon_id": str(h.id),
                "hackathon_title": h.title,
                "position": p["position"],
                "prize_title": p["title"],
                "winner_team": winner_team,
                "winner_project": winner_project,
                "prize_amount": f"{Decimal(str(p['amount'] or 0)):,.2f} {currency}",
                "total_budget": f"{Decimal(str(total_budget)):,.2f} {currency}",
            })
    return rows


def get_analytics_data(hackathons):
    """Computes high-level KPI and demographic analytics."""
    rows = []
    for h in hackathons:
        total_regs = h.registrations.filter(withdrawn_at__isnull=True).count()
        total_teams = h.teams.count()
        total_subs = h.submissions.filter(submitted_at__isnull=True).count()
        sub_rate = round((total_subs / total_regs * 100), 1) if total_regs > 0 else 0
        team_rate = round((total_teams * 3 / total_regs * 100), 1) if total_regs > 0 else 0

        # Demographics from custom answers
        roles = {}
        cities = {}
        for reg in h.registrations.filter(withdrawn_at__isnull=True):
            p = (reg.custom_answers or {}).get("personalInfo", {})
            r = p.get("role") or "Software Developer"
            c = p.get("city") or "Addis Ababa"
            roles[r] = roles.get(r, 0) + 1
            cities[c] = cities.get(c, 0) + 1

        top_role = max(roles, key=roles.get) if roles else "N/A"
        top_city = max(cities, key=cities.get) if cities else "Addis Ababa"

        rows.append({
            "hackathon_id": str(h.id),
            "hackathon_title": h.title,
            "field": h.field or "Technology",
            "total_registrations": total_regs,
            "total_teams": total_teams,
            "total_submissions": total_subs,
            "submission_rate": f"{sub_rate}%",
            "team_formation_rate": f"{team_rate}%",
            "top_participant_role": top_role,
            "top_location": top_city,
            "open_to": ", ".join(h.open_to) if h.open_to else "Everyone",
        })
    return rows


# ==============================================================================
# EXCEL GENERATION (.xlsx)
# ==============================================================================

def generate_excel_export(hackathons, resource="complete", filters=None):
    """Creates a styled Excel workbook."""
    wb = Workbook()
    # Remove default active sheet if creating multi-sheet
    wb.remove(wb.active)

    if resource == "complete":
        # Sheet 1: Overview
        ws_over = wb.create_sheet(title="Overview")
        ws_over.append(["Hackathon Title", "Field / Industry", "Location", "Venue", "Eligibility (Open To)", "Tags", "Prize Budget", "Registration Window", "Submission Window", "Status"])
        _style_header_row(ws_over)
        for h in hackathons:
            dates_reg = f"{h.registration_opens_at.strftime('%Y-%m-%d')} to {h.registration_closes_at.strftime('%Y-%m-%d')}" if (getattr(h, 'registration_opens_at', None) and getattr(h, 'registration_closes_at', None)) else "Ongoing / Open"
            dates_sub = f"{h.submission_opens_at.strftime('%Y-%m-%d')} to {h.submission_closes_at.strftime('%Y-%m-%d')}" if (getattr(h, 'submission_opens_at', None) and getattr(h, 'submission_closes_at', None)) else "Open"
            tags_str = ", ".join(h.tags) if getattr(h, 'tags', None) else "Innovation"
            open_str = ", ".join(h.open_to) if getattr(h, 'open_to', None) else "Everyone"
            ws_over.append([
                h.title,
                h.field or "Technology",
                h.location_name or h.location_mode or "Online",
                h.venue or "N/A",
                open_str,
                tags_str,
                f"{h.total_prize_budget:,.2f}" if h.total_prize_budget else "$0.00",
                dates_reg,
                dates_sub,
                h.status.capitalize(),
            ])
        _auto_adjust_columns(ws_over)

        # Sheet 2: Participants
        ws_part = wb.create_sheet(title="Participants")
        ws_part.append(["Participant Name", "Email", "Phone", "Country", "City", "University / Organization", "Role", "Experience", "Skills", "LinkedIn", "GitHub", "Team Name", "Status", "Eligibility Confirmed", "Referral Source", "Registered At", "Hackathon"])
        _style_header_row(ws_part)
        for p in get_participants_data(hackathons, filters):
            ws_part.append([
                p["full_name"], p["email"], p["phone"], p["country"], p["city"], p["organization"], p["role"], p["experience"], p["skills"], p["linkedin"], p["github"], p["team_name"], p["status"], p["eligibility_confirmed"], p["referral_source"], p["registered_at"], p["hackathon_title"],
            ])
        _auto_adjust_columns(ws_part)

        # Sheet 3: Teams
        ws_teams = wb.create_sheet(title="Teams")
        ws_teams.append(["Team Name", "Leader Name", "Leader Email", "Team Size", "Members", "Submission", "Open To Join", "Status", "Created At", "Hackathon"])
        _style_header_row(ws_teams)
        for t in get_teams_data(hackathons, filters):
            ws_teams.append([
                t["team_name"], t["leader_name"], t["leader_email"], t["team_size"], t["member_names"], t["submission_title"], t["open_to_members"], t["status"], t["created_at"], t["hackathon_title"],
            ])
        _auto_adjust_columns(ws_teams)

        # Sheet 4: Submissions
        ws_subs = wb.create_sheet(title="Submissions")
        ws_subs.append(["Project Title", "Team Name", "Tagline", "Technologies", "GitHub / Repo", "Demo URL", "Status", "Submitted At", "Hackathon"])
        _style_header_row(ws_subs)
        for s in get_submissions_data(hackathons, filters):
            ws_subs.append([
                s["project_title"], s["team_name"], s["tagline"], s["technologies"], s["repo_url"], s["demo_url"], s["status"], s["submitted_at"], s["hackathon_title"],
            ])
        _auto_adjust_columns(ws_subs)

        # Sheet 5: Judging
        ws_judge = wb.create_sheet(title="Judging")
        ws_judge.append(["Project Title", "Team Name", "Judge Name", "Judge Email", "Total Score", "Average Score", "Evaluation Status", "Feedback Comments", "Hackathon"])
        _style_header_row(ws_judge)
        for j in get_judging_data(hackathons, filters):
            ws_judge.append([
                j["project_title"], j["team_name"], j["judge_name"], j["judge_email"], j["total_score"], j["average_score"], j["status"], j["comments"], j["hackathon_title"],
            ])
        _auto_adjust_columns(ws_judge)

        # Sheet 6: Prizes
        ws_prizes = wb.create_sheet(title="Prizes")
        ws_prizes.append(["Position", "Prize Title", "Winner Team", "Winning Project", "Prize Amount", "Total Budget", "Hackathon"])
        _style_header_row(ws_prizes)
        for p in get_prizes_data(hackathons):
            ws_prizes.append([
                p["position"], p["prize_title"], p["winner_team"], p["winner_project"], p["prize_amount"], p["total_budget"], p["hackathon_title"],
            ])
        _auto_adjust_columns(ws_prizes)

        # Sheet 7: Analytics
        ws_anal = wb.create_sheet(title="Analytics")
        ws_anal.append(["Hackathon", "Field / Domain", "Total Registrations", "Total Teams", "Total Submissions", "Submission Rate", "Team Formation Rate", "Top Role", "Top Location"])
        _style_header_row(ws_anal)
        for a in get_analytics_data(hackathons):
            ws_anal.append([
                a["hackathon_title"], a["field"], a["total_registrations"], a["total_teams"], a["total_submissions"], a["submission_rate"], a["team_formation_rate"], a["top_participant_role"], a["top_location"],
            ])
        _auto_adjust_columns(ws_anal)

    elif resource == "participants":
        ws = wb.create_sheet(title="Participants")
        ws.append(["Participant Name", "Email", "Phone", "City / Country", "University / Organization", "Role", "Team Name", "Status", "Eligibility Confirmed", "Referral Source", "Registered At", "Hackathon"])
        _style_header_row(ws)
        for p in get_participants_data(hackathons, filters):
            ws.append([p["full_name"], p["email"], p["phone"], p["city"], p["organization"], p["role"], p["team_name"], p["status"], p["eligibility_confirmed"], p["referral_source"], p["registered_at"], p["hackathon_title"]])
        _auto_adjust_columns(ws)

    elif resource == "teams":
        ws = wb.create_sheet(title="Teams")
        ws.append(["Team Name", "Leader Name", "Leader Email", "Team Size", "Members", "Submission", "Open To Join", "Status", "Created At", "Hackathon"])
        _style_header_row(ws)
        for t in get_teams_data(hackathons, filters):
            ws.append([t["team_name"], t["leader_name"], t["leader_email"], t["team_size"], t["member_names"], t["submission_title"], t["open_to_members"], t["status"], t["created_at"], t["hackathon_title"]])
        _auto_adjust_columns(ws)

    elif resource == "submissions":
        ws = wb.create_sheet(title="Submissions")
        ws.append(["Project Title", "Team Name", "Tagline", "Technologies", "GitHub / Repo", "Demo URL", "Status", "Submitted At", "Hackathon"])
        _style_header_row(ws)
        for s in get_submissions_data(hackathons, filters):
            ws.append([s["project_title"], s["team_name"], s["tagline"], s["technologies"], s["repo_url"], s["demo_url"], s["status"], s["submitted_at"], s["hackathon_title"]])
        _auto_adjust_columns(ws)

    elif resource == "judging":
        ws = wb.create_sheet(title="Judging Results")
        ws.append(["Project Title", "Team Name", "Judge Name", "Judge Email", "Total Score", "Average Score", "Evaluation Status", "Feedback Comments", "Hackathon"])
        _style_header_row(ws)
        for j in get_judging_data(hackathons, filters):
            ws.append([j["project_title"], j["team_name"], j["judge_name"], j["judge_email"], j["total_score"], j["average_score"], j["status"], j["comments"], j["hackathon_title"]])
        _auto_adjust_columns(ws)

    elif resource == "prizes":
        ws = wb.create_sheet(title="Prizes & Winners")
        ws.append(["Position", "Prize Title", "Winner Team", "Winning Project", "Prize Amount", "Total Budget", "Hackathon"])
        _style_header_row(ws)
        for p in get_prizes_data(hackathons):
            ws.append([p["position"], p["prize_title"], p["winner_team"], p["winner_project"], p["prize_amount"], p["total_budget"], p["hackathon_title"]])
        _auto_adjust_columns(ws)

    elif resource == "analytics":
        ws = wb.create_sheet(title="Analytics Report")
        ws.append(["Hackathon", "Field / Domain", "Total Registrations", "Total Teams", "Total Submissions", "Submission Rate", "Team Formation Rate", "Top Role", "Top Location"])
        _style_header_row(ws)
        for a in get_analytics_data(hackathons):
            ws.append([a["hackathon_title"], a["field"], a["total_registrations"], a["total_teams"], a["total_submissions"], a["submission_rate"], a["team_formation_rate"], a["top_participant_role"], a["top_location"]])
        _auto_adjust_columns(ws)

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream.getvalue()


# ==============================================================================
# CSV GENERATION (.csv)
# ==============================================================================

def generate_csv_export(hackathons, resource="participants", filters=None):
    """Generates standard RFC-4180 UTF-8 CSV with Excel BOM for international character compatibility."""
    stream = io.StringIO()
    writer = csv.writer(stream, dialect="excel")

    if resource in ["participants", "complete"]:
        writer.writerow(["Participant Name", "Email", "Phone", "Country", "City", "University / Organization", "Role", "Experience", "Skills", "LinkedIn", "GitHub", "Team Name", "Status", "Eligibility Confirmed", "Referral Source", "Registered At", "Hackathon"])
        for p in get_participants_data(hackathons, filters):
            writer.writerow([p["full_name"], p["email"], p["phone"], p["country"], p["city"], p["organization"], p["role"], p["experience"], p["skills"], p["linkedin"], p["github"], p["team_name"], p["status"], p["eligibility_confirmed"], p["referral_source"], p["registered_at"], p["hackathon_title"]])

    elif resource == "teams":
        writer.writerow(["Team Name", "Leader Name", "Leader Email", "Team Size", "Members", "Submission", "Open To Join", "Status", "Created At", "Hackathon"])
        for t in get_teams_data(hackathons, filters):
            writer.writerow([t["team_name"], t["leader_name"], t["leader_email"], t["team_size"], t["member_names"], t["submission_title"], t["open_to_members"], t["status"], t["created_at"], t["hackathon_title"]])

    elif resource == "submissions":
        writer.writerow(["Project Title", "Team Name", "Tagline", "Technologies", "GitHub / Repo", "Demo URL", "Status", "Submitted At", "Hackathon"])
        for s in get_submissions_data(hackathons, filters):
            writer.writerow([s["project_title"], s["team_name"], s["tagline"], s["technologies"], s["repo_url"], s["demo_url"], s["status"], s["submitted_at"], s["hackathon_title"]])

    elif resource == "judging":
        writer.writerow(["Project Title", "Team Name", "Judge Name", "Judge Email", "Total Score", "Average Score", "Evaluation Status", "Feedback Comments", "Hackathon"])
        for j in get_judging_data(hackathons, filters):
            writer.writerow([j["project_title"], j["team_name"], j["judge_name"], j["judge_email"], j["total_score"], j["average_score"], j["status"], j["comments"], j["hackathon_title"]])

    elif resource == "prizes":
        writer.writerow(["Position", "Prize Title", "Winner Team", "Winning Project", "Prize Amount", "Total Budget", "Hackathon"])
        for p in get_prizes_data(hackathons):
            writer.writerow([p["position"], p["prize_title"], p["winner_team"], p["winner_project"], p["prize_amount"], p["total_budget"], p["hackathon_title"]])

    elif resource == "analytics":
        writer.writerow(["Hackathon", "Field / Domain", "Total Registrations", "Total Teams", "Total Submissions", "Submission Rate", "Team Formation Rate", "Top Role", "Top Location"])
        for a in get_analytics_data(hackathons):
            writer.writerow([a["hackathon_title"], a["field"], a["total_registrations"], a["total_teams"], a["total_submissions"], a["submission_rate"], a["team_formation_rate"], a["top_participant_role"], a["top_location"]])

    # Prefix UTF-8 BOM so Excel opens CSVs cleanly
    return "\ufeff" + stream.getvalue()


# ==============================================================================
# PDF REPORT GENERATION (.pdf)
# ==============================================================================

def generate_pdf_export(hackathons, resource="complete", filters=None):
    """Creates a high-end styled executive summary PDF report."""
    stream = io.BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=landscape(letter),
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F6B5C"),
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#57685F"),
    )
    section_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0F6B5C"),
        fontName="Helvetica-Bold",
        spaceBefore=14,
        spaceAfter=6,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#122622"),
    )
    cell_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    story = []

    # Title & Metadata Header
    main_title = hackathons[0].title if len(hackathons) == 1 else "HODANA Innovation Hub — Managed Hackathons Report"
    story.append(Paragraph(main_title, title_style))
    story.append(Paragraph(f"Exported on {datetime.now().strftime('%B %d, %Y at %H:%M UTC')} • Official Event Summary Report", subtitle_style))
    story.append(Spacer(1, 16))

    if resource in ["complete", "analytics"]:
        story.append(Paragraph("1. Executive Summary & Key Performance Metrics", section_style))
        analytics = get_analytics_data(hackathons)
        table_data = [[
            Paragraph("Hackathon", cell_header_style),
            Paragraph("Field", cell_header_style),
            Paragraph("Registrations", cell_header_style),
            Paragraph("Teams", cell_header_style),
            Paragraph("Submissions", cell_header_style),
            Paragraph("Submission Rate", cell_header_style),
            Paragraph("Top Role", cell_header_style),
            Paragraph("Top Location", cell_header_style),
        ]]
        for a in analytics:
            table_data.append([
                Paragraph(a["hackathon_title"], cell_style),
                Paragraph(a["field"], cell_style),
                Paragraph(str(a["total_registrations"]), cell_style),
                Paragraph(str(a["total_teams"]), cell_style),
                Paragraph(str(a["total_submissions"]), cell_style),
                Paragraph(a["submission_rate"], cell_style),
                Paragraph(a["top_participant_role"], cell_style),
                Paragraph(a["top_location"], cell_style),
            ])

        t = Table(table_data, colWidths=[150, 80, 70, 50, 70, 80, 110, 110])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F6B5C")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D6E7E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAF9")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
        story.append(Spacer(1, 14))

    if resource in ["complete", "participants"]:
        story.append(Paragraph("2. Participant Registrations", section_style))
        participants = get_participants_data(hackathons, filters)
        p_table_data = [[
            Paragraph("Name", cell_header_style),
            Paragraph("Email", cell_header_style),
            Paragraph("City", cell_header_style),
            Paragraph("Organization", cell_header_style),
            Paragraph("Role", cell_header_style),
            Paragraph("Team", cell_header_style),
            Paragraph("Status", cell_header_style),
        ]]
        for p in participants[:100]:  # Cap at 100 rows for PDF layout
            p_table_data.append([
                Paragraph(p["full_name"], cell_style),
                Paragraph(p["email"], cell_style),
                Paragraph(p["city"], cell_style),
                Paragraph(p["organization"], cell_style),
                Paragraph(p["role"], cell_style),
                Paragraph(p["team_name"], cell_style),
                Paragraph(p["status"], cell_style),
            ])
        pt = Table(p_table_data, colWidths=[110, 130, 80, 130, 110, 100, 60])
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F6B5C")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D6E7E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAF9")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(pt)
        story.append(Spacer(1, 14))

    if resource in ["complete", "submissions"]:
        story.append(Paragraph("3. Project Submissions & Prototypes", section_style))
        submissions = get_submissions_data(hackathons, filters)
        s_table_data = [[
            Paragraph("Project", cell_header_style),
            Paragraph("Team", cell_header_style),
            Paragraph("Technologies", cell_header_style),
            Paragraph("Repo Link", cell_header_style),
            Paragraph("Status", cell_header_style),
            Paragraph("Submitted", cell_header_style),
        ]]
        for s in submissions[:60]:
            s_table_data.append([
                Paragraph(s["project_title"], cell_style),
                Paragraph(s["team_name"], cell_style),
                Paragraph(s["technologies"], cell_style),
                Paragraph(s["repo_url"], cell_style),
                Paragraph(s["status"], cell_style),
                Paragraph(s["submitted_at"], cell_style),
            ])
        st = Table(s_table_data, colWidths=[140, 110, 160, 170, 60, 80])
        st.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F6B5C")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D6E7E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAF9")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(st)
        story.append(Spacer(1, 14))

    if resource in ["complete", "prizes"]:
        story.append(Paragraph("4. Prize Allocations & Winners", section_style))
        prizes = get_prizes_data(hackathons)
        pr_table_data = [[
            Paragraph("Position", cell_header_style),
            Paragraph("Prize Tier", cell_header_style),
            Paragraph("Winner Team", cell_header_style),
            Paragraph("Winning Project", cell_header_style),
            Paragraph("Prize Amount", cell_header_style),
        ]]
        for pr in prizes:
            pr_table_data.append([
                Paragraph(pr["position"], cell_style),
                Paragraph(pr["prize_title"], cell_style),
                Paragraph(pr["winner_team"], cell_style),
                Paragraph(pr["winner_project"], cell_style),
                Paragraph(pr["prize_amount"], cell_style),
            ])
        prt = Table(pr_table_data, colWidths=[90, 130, 150, 200, 150])
        prt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F6B5C")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D6E7E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAF9")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(prt)

    doc.build(story)
    stream.seek(0)
    return stream.getvalue()
