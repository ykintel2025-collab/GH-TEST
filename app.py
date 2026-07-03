"""
app.py
Streamlit UI voor het High-Performance Asset Management dashboard.
Draaien met: streamlit run app.py
Vereist st.secrets["DB_URL"] en st.secrets["credentials"].
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from urllib.parse import quote
import database as db
import auth
import emailer

st.set_page_config(
    page_title="GH2026 (TEST)" if st.secrets.get("ENV", "production").lower() == "test" else "Asset Management Dashboard",
    layout="wide",
    page_icon="🧪" if st.secrets.get("ENV", "production").lower() == "test" else "📊",
)

# --- Omgeving herkennen (test vs. live) -----------------------------------
ENV = st.secrets.get("ENV", "production")
IS_TEST = ENV.lower() == "test"

if IS_TEST:
    st.markdown(
        """
        <div style='background-color:#ff4b4b;color:white;padding:10px;
                    text-align:center;font-weight:bold;border-radius:6px;
                    margin-bottom:10px;'>
            🧪 TESTOMGEVING — wijzigingen hier zijn NIET zichtbaar in de live app
        </div>
        """,
        unsafe_allow_html=True,
    )

# --- Login ---------------------------------------------------------------
current_user = auth.check_login()

# --- Database init (idempotent, veilig om elke keer te draaien) ----------
db.init_db()

PRIORITIES = ["A", "B", "C"]
STATUSES = ["Open", "Paid"]
PIPELINE_STATUSES = ["Lead", "Pitch", "Deal"]
ASSIGNEES = ["Ibrahim", "Seal", "Glenn"]
TASK_STATUSES = ["Open", "Done"]


def eur(x):
    try:
        return f"€ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "€ 0,00"


def prio_badge(p):
    colors = {"A": "🔴", "B": "🟡", "C": "🟢"}
    return f"{colors.get(p, '⚪')} {p}"


def whatsapp_link(phone, text=""):
    """Bouwt een wa.me-link. Verwacht telefoonnummer met of zonder +/spaties;
    een nummer dat met 0 begint wordt aangenomen als Nederlands (0 -> 31)."""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0"):
        digits = "31" + digits[1:]
    if not digits:
        return None
    url = f"https://wa.me/{digits}"
    if text:
        url += f"?text={quote(text)}"
    return url


def mailto_link(email, subject="", body=""):
    if not email:
        return None
    url = f"mailto:{email}"
    params = []
    if subject:
        params.append(f"subject={quote(subject)}")
    if body:
        params.append(f"body={quote(body)}")
    if params:
        url += "?" + "&".join(params)
    return url


def fill_template(text, debt):
    """Vervangt {naam} in een sjabloon door de naam van de schuldeiser."""
    if not text:
        return text
    return text.replace("{naam}", debt.get("creditor_name", ""))


def contact_type_picker(key_prefix, current_value=None):
    """Toont bestaande contacttypes als keuze + optie om een nieuw type te typen."""
    existing = db.get_contact_types()
    options = existing + ["➕ Nieuw type..."]
    default_index = existing.index(current_value) if current_value in existing else len(options) - 1
    choice = st.selectbox("Type contact", options, index=default_index, key=f"{key_prefix}_typechoice")
    if choice == "➕ Nieuw type...":
        return st.text_input("Nieuw type (bijv. 'Hulpverlening', 'Accountant')", value=current_value or "", key=f"{key_prefix}_newtype")
    return choice


# --- Sidebar navigatie -----------------------------------------------------
with st.sidebar:
    if IS_TEST:
        st.markdown("### 🧪 TEST")
    st.write(f"Ingelogd als **{current_user}**")
    if st.button("Uitloggen"):
        st.session_state["authenticated"] = False
        st.session_state["user"] = None
        st.rerun()
    st.divider()
    page = st.radio(
        "Navigatie",
        ["🏠 Dashboard", "👥 Contacten", "💰 Financieel", "✅ Taken", "⚙️ Beheer"],
        label_visibility="collapsed",
    )

# ===========================================================================
# PAGINA: DASHBOARD
# ===========================================================================
if page == "🏠 Dashboard":
    st.title(f"Welkom terug, {current_user} 👋")
    st.caption("Financieel overzicht vind je onder 💰 Financieel.")

    st.subheader("🗓️ Wat er speelt")
    with st.popover("➕ Snel een taak toevoegen"):
        with st.form("dash_add_task", clear_on_submit=True):
            t_title = st.text_input("Taak (bijv. 'Bel Fiscus')")
            t_assignee = st.selectbox("Toewijzen aan", ASSIGNEES, index=ASSIGNEES.index(current_user) if current_user in ASSIGNEES else 0)
            t_due = st.date_input("Deadline", value=date.today())
            t_desc = st.text_area("Toelichting (optioneel)")
            if st.form_submit_button("Taak toevoegen") and t_title:
                db.add_task(t_title, t_assignee, current_user, description=t_desc or None, due_date=t_due)
                st.rerun()

    all_open_tasks = db.get_tasks(status="Open")
    tasks_no_date = [t for t in all_open_tasks if not t["due_date"]]
    tasks_with_date = [t for t in all_open_tasks if t["due_date"]]

    if tasks_no_date:
        st.markdown("**⚪ Taken zonder datum**")
        for t in tasks_no_date:
            cols = st.columns([0.06, 0.7, 0.24])
            done = cols[0].checkbox("", key=f"nodate_task_{t['id']}")
            label = f"**{t['title']}** — _{t['assigned_to']}_"
            if t.get("creditor_name"):
                label += f"  ·  {t['creditor_name']}"
            cols[1].markdown(label)
            if done:
                db.update_task(t["id"], status="Done")
                st.rerun()

    # Agenda: taken (met datum), lopende kosten en betaaldatums van schulden, samen gegroepeerd
    agenda_items = []
    for t in tasks_with_date:
        agenda_items.append({
            "date": t["due_date"], "kind": "task", "id": t["id"],
            "label": f"✅ {t['title']}", "detail": t["assigned_to"],
        })
    for c in db.get_running_costs(status="Open"):
        if c["due_date"]:
            agenda_items.append({"date": c["due_date"], "kind": "cost", "label": f"🧾 {c['name']}", "detail": eur(c["amount"])})
    for d in db.get_debts(status="Open"):
        if d.get("next_payment_date"):
            agenda_items.append({
                "date": d["next_payment_date"], "kind": "debt", "label": f"📌 Betaling {d['creditor_name']}",
                "detail": d.get("payment_agreement") or eur(d["current_amount"]),
            })

    if not agenda_items and not tasks_no_date:
        st.info("Niks gepland — geen openstaande taken, kosten of betaaldatums.")
    elif agenda_items:
        agenda_items.sort(key=lambda x: x["date"])
        view_mode = st.radio("Weergave", ["Per week", "Per maand"], horizontal=True, key="dash_agenda_view")

        today = date.today()
        groups = {}
        for item in agenda_items:
            if view_mode == "Per week":
                year, week, _ = item["date"].isocalendar()
                key = f"Week {week} — {year}"
            else:
                key = item["date"].strftime("%B %Y")
            groups.setdefault(key, []).append(item)

        for key, items in groups.items():
            st.markdown(f"**{key}**")
            for item in items:
                prefix = "🔴 " if item["date"] < today else ""
                if item["kind"] == "task":
                    tcol1, tcol2 = st.columns([0.06, 0.94])
                    done = tcol1.checkbox("", key=f"agenda_task_{item['id']}")
                    tcol2.write(f"{prefix}`{item['date'].strftime('%d-%m')}` {item['label']} — {item['detail']}")
                    if done:
                        db.update_task(item["id"], status="Done")
                        st.rerun()
                else:
                    st.write(f"{prefix}`{item['date'].strftime('%d-%m')}` {item['label']} — {item['detail']}")
            st.divider()

    st.divider()
    st.subheader("🕒 Recente activiteit")
    activity = db.get_recent_activity(limit=6)
    if not activity:
        st.caption("Nog geen activiteit gelogd.")
    else:
        for a in activity:
            datum = a["date"].strftime("%d-%m")
            if a["kind"] == "payment":
                st.caption(f"💶 `{datum}` **{a['logged_by']}** registreerde een betaling van {eur(a['amount'])} bij *{a['creditor_name']}*")
            else:
                st.caption(f"📝 `{datum}` **{a['logged_by']}** noteerde bij *{a['creditor_name']}*: {a['note']}")

# ===========================================================================
# PAGINA: CONTACTEN (schuldeisers, hulpverlening, accountants, overig)
# ===========================================================================
elif page == "👥 Contacten":
    top1, top2 = st.columns([4, 1])
    with top1:
        st.title("Contacten")
    with top2:
        with st.popover("➕ Nieuw contact"):
            with st.form("add_contact_form", clear_on_submit=True):
                name = st.text_input("Naam")
                contact_type = contact_type_picker("addcontact")
                organization = st.text_input("Organisatie (optioneel)")
                address = st.text_input("Adres")
                acol1, acol2 = st.columns(2)
                postal_code = acol1.text_input("Postcode")
                city = acol2.text_input("Plaats")
                phone = st.text_input("Telefoonnummer")
                email = st.text_input("E-mailadres")
                notes = st.text_area("Notities")
                if st.form_submit_button("Toevoegen") and name:
                    db.add_contact(
                        name, contact_type=contact_type or None, organization=organization or None,
                        address=address or None, postal_code=postal_code or None, city=city or None,
                        phone=phone or None, email=email or None, notes=notes or None, created_by=current_user,
                    )
                    st.rerun()

    all_types = ["Alle"] + db.get_contact_types()
    type_filter = st.selectbox("Filter op type", all_types)
    contacts = db.get_contacts(contact_type=None if type_filter == "Alle" else type_filter)

    search_c = st.text_input("Zoek op naam", placeholder="Zoek contact...")
    if search_c:
        contacts = [c for c in contacts if search_c.lower() in c["name"].lower()]

    if not contacts:
        st.info("Geen contacten gevonden.")
    else:
        st.caption(f"{len(contacts)} contacten")
        for c in contacts:
            label = f"**{c['name']}**"
            if c.get("contact_type"):
                label += f"  ·  _{c['contact_type']}_"
            with st.expander(label):
                with st.form(f"edit_contact_{c['id']}"):
                    e_name = st.text_input("Naam", value=c["name"], key=f"cname_{c['id']}")
                    e_type = contact_type_picker(f"edit_{c['id']}", current_value=c.get("contact_type"))
                    e_org = st.text_input("Organisatie", value=c.get("organization") or "", key=f"corg_{c['id']}")
                    e_address = st.text_input("Adres", value=c.get("address") or "", key=f"cadr_{c['id']}")
                    ec1, ec2 = st.columns(2)
                    e_postal = ec1.text_input("Postcode", value=c.get("postal_code") or "", key=f"cpc_{c['id']}")
                    e_city = ec2.text_input("Plaats", value=c.get("city") or "", key=f"ccity_{c['id']}")
                    e_phone = st.text_input("Telefoonnummer", value=c.get("phone") or "", key=f"cphone_{c['id']}")
                    e_email = st.text_input("E-mailadres", value=c.get("email") or "", key=f"cemail_{c['id']}")
                    e_notes = st.text_area("Notities", value=c.get("notes") or "", key=f"cnotes_{c['id']}")
                    save_col, del_col = st.columns(2)
                    if save_col.form_submit_button("💾 Opslaan"):
                        db.update_contact(
                            c["id"], name=e_name, contact_type=e_type or None, organization=e_org or None,
                            address=e_address or None, postal_code=e_postal or None, city=e_city or None,
                            phone=e_phone or None, email=e_email or None, notes=e_notes or None,
                        )
                        st.rerun()
                    if del_col.form_submit_button("🗑️ Verwijderen"):
                        success, error = db.delete_contact(c["id"])
                        if success:
                            st.rerun()
                        else:
                            st.error(error)

# ===========================================================================
# PAGINA: TAKEN (volledig beheer)
# ===========================================================================
elif page == "✅ Taken":
    st.title("Taken")

    with st.popover("➕ Nieuwe taak"):
        with st.form("new_task_form", clear_on_submit=True):
            title = st.text_input("Titel")
            assignee = st.selectbox("Toewijzen aan", ASSIGNEES)
            due = st.date_input("Deadline", value=date.today())
            desc = st.text_area("Toelichting (optioneel)")
            debts_all = db.get_debts()
            debt_options = {"— geen —": None}
            debt_options.update({d["creditor_name"]: d["id"] for d in debts_all})
            linked = st.selectbox("Koppelen aan schuldeiser (optioneel)", list(debt_options.keys()))
            if st.form_submit_button("Toevoegen") and title:
                db.add_task(title, assignee, current_user, description=desc or None, due_date=due, related_debt_id=debt_options[linked])
                st.rerun()

    fcol1, fcol2 = st.columns(2)
    filter_assignee = fcol1.selectbox("Filter op persoon", ["Iedereen"] + ASSIGNEES)
    filter_status = fcol2.selectbox("Filter op status", ["Alle", "Open", "Done"])

    tasks = db.get_tasks(
        assigned_to=None if filter_assignee == "Iedereen" else filter_assignee,
        status=None if filter_status == "Alle" else filter_status,
    )

    if not tasks:
        st.info("Geen taken gevonden.")
    else:
        for t in tasks:
            cols = st.columns([0.06, 0.5, 0.15, 0.15, 0.14])
            done = cols[0].checkbox("", value=(t["status"] == "Done"), key=f"taskpage_{t['id']}")
            title_txt = f"~~{t['title']}~~" if t["status"] == "Done" else f"**{t['title']}**"
            if t.get("creditor_name"):
                title_txt += f" — _{t['creditor_name']}_"
            cols[1].markdown(title_txt)
            if t["description"]:
                cols[1].caption(t["description"])
            cols[2].write(t["assigned_to"])
            cols[3].write(t["due_date"].strftime("%d-%m-%Y") if t["due_date"] else "—")
            if cols[4].button("🗑️", key=f"deltask_{t['id']}"):
                db.delete_task(t["id"])
                st.rerun()

            new_status = "Done" if done else "Open"
            if new_status != t["status"]:
                db.update_task(t["id"], status=new_status)
                st.rerun()


# ===========================================================================
# PAGINA: FINANCIEEL (Pipeline & Inkomsten / Lopende kosten / Privé / Liquiditeit)
# ===========================================================================
elif page == "💰 Financieel":
    st.title("Financieel")
    sub_page = st.selectbox(
        "Onderdeel",
        [
            "📋 Schulden", "📈 Pipeline & Inkomsten", "🚀 Business Cases",
            "🧾 Lopende kosten", "🏠 Privé-uitgaven", "💧 Liquiditeitsbegroting",
        ],
        label_visibility="collapsed",
    )
    st.divider()

    # --- Onderdeel: Schulden -------------------------------------------------
    if sub_page == "📋 Schulden":
        top1, top2 = st.columns([4, 1])
        with top1:
            st.title("Schulden Overzicht")
        with top2:
            with st.popover("➕ Nieuwe schuld"):
                existing_contacts = db.get_contacts()
                contact_choice_options = ["➕ Nieuw contact aanmaken"] + [c["name"] for c in existing_contacts]
                chosen = st.selectbox("Schuldeiser", contact_choice_options, key="new_debt_contact_choice")

                with st.form("add_debt_form", clear_on_submit=True):
                    if chosen == "➕ Nieuw contact aanmaken":
                        new_name = st.text_input("Naam")
                        new_type = st.text_input("Type contact", value="Schuldeiser")
                        address = st.text_input("Adres")
                        acol1, acol2 = st.columns(2)
                        postal_code = acol1.text_input("Postcode")
                        city = acol2.text_input("Plaats")
                        phone = st.text_input("Telefoonnummer", placeholder="06 12345678")
                        email = st.text_input("E-mailadres")
                    else:
                        new_name = None

                    total_amount = st.number_input("Hoofdsom oorspronkelijk", min_value=0.0, step=100.0)
                    current_amount = st.number_input("Actueel bedrag", min_value=0.0, step=100.0)
                    priority = st.selectbox("Prioriteit", PRIORITIES)

                    if st.form_submit_button("Toevoegen"):
                        if chosen == "➕ Nieuw contact aanmaken" and new_name:
                            contact_id = db.add_contact(
                                new_name, contact_type=new_type or "Schuldeiser",
                                address=address or None, postal_code=postal_code or None,
                                city=city or None, phone=phone or None, email=email or None,
                                created_by=current_user,
                            )
                        elif chosen != "➕ Nieuw contact aanmaken":
                            contact_id = next(c["id"] for c in existing_contacts if c["name"] == chosen)
                        else:
                            contact_id = None

                        if contact_id:
                            db.add_debt(contact_id, total_amount, current_amount, priority)
                            st.success("Schuld toegevoegd.")
                            st.rerun()

        totals = db.get_totals()
        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric("Netto positie", eur(totals["net_position"]))
        tc2.metric("Schulden (open)", eur(totals["total_debt_current"]))
        tc3.metric("Al afgelost", eur(db.get_total_paid()))
        if totals["total_debt_original"] > 0:
            afgelost = totals["total_debt_original"] - totals["total_debt_current"]
            pct = max(0.0, min(1.0, afgelost / totals["total_debt_original"]))
            tc4.metric("Voortgang sanering", f"{pct*100:.1f}%")
        st.divider()

        fc1, fc2 = st.columns([1, 3])
        status_filter = fc1.radio("Filter", ["Alle", "Open", "Paid"], horizontal=True, label_visibility="collapsed")
        search = fc2.text_input("Zoek op naam", placeholder="Zoek schuldeiser...", label_visibility="collapsed")

        debts = db.get_debts(status=None if status_filter == "Alle" else status_filter)
        if search:
            debts = [d for d in debts if search.lower() in d["creditor_name"].lower()]

        if not debts:
            st.info("Geen schulden gevonden.")
        else:
            st.caption(f"{len(debts)} schuldeisers")

            # Logs, betalingen en taken 1x ophalen en per schuld groeperen
            # (i.p.v. voor elke schuldeiser apart de database te bevragen)
            logs_by_debt = {}
            for l in db.get_all_debt_logs():
                logs_by_debt.setdefault(l["debt_id"], []).append(l)

            payments_by_debt = {}
            for p in db.get_all_payments():
                payments_by_debt.setdefault(p["debt_id"], []).append(p)

            tasks_by_debt = {}
            for t in db.get_tasks():
                tasks_by_debt.setdefault(t["related_debt_id"], []).append(t)

            for debt in debts:
                last_contact = debt["last_contact"].strftime("%d-%m-%Y") if debt["last_contact"] else "—"
                header = (
                    f"{prio_badge(debt['priority'])}  **{debt['creditor_name']}**  "
                    f"—  {eur(debt['current_amount'])}  ·  {debt['status']}  ·  laatst contact {last_contact}"
                )
                if debt.get("payment_agreement"):
                    header += f"  ·  📌 _{debt['payment_agreement']}_"
                with st.expander(header):
                    dc1, dc2, dc3, dc4 = st.columns(4)

                    with dc1:
                        new_amount = st.number_input(
                            "Actueel bedrag", min_value=0.0, value=float(debt["current_amount"]),
                            step=50.0, key=f"amt_{debt['id']}",
                        )
                    with dc2:
                        new_status = st.selectbox(
                            "Status", STATUSES,
                            index=STATUSES.index(debt["status"]) if debt["status"] in STATUSES else 0,
                            key=f"status_{debt['id']}",
                        )
                    with dc3:
                        new_priority = st.selectbox(
                            "Prioriteit", PRIORITIES,
                            index=PRIORITIES.index(debt["priority"]) if debt["priority"] in PRIORITIES else 1,
                            key=f"prio_{debt['id']}",
                        )
                    with dc4:
                        st.write("")
                        st.write("")
                        bcol1, bcol2 = st.columns(2)
                        if bcol1.button("💾 Opslaan", key=f"save_{debt['id']}"):
                            db.update_debt(debt["id"], current_amount=new_amount, status=new_status, priority=new_priority)
                            st.rerun()
                        if bcol2.button("🗑️", key=f"del_{debt['id']}", help="Schuld verwijderen"):
                            db.delete_debt(debt["id"])
                            st.rerun()

                    agcol1, agcol2 = st.columns([2, 1])
                    new_agreement = agcol1.text_input(
                        "📌 Betalingsafspraak (bijv. '€500 per maand', 'Zsm', '50K per 31 aug')",
                        value=debt.get("payment_agreement") or "", key=f"agreement_{debt['id']}",
                    )
                    new_next_date = agcol2.date_input(
                        "Volgende betaaldatum (voor agenda)",
                        value=debt.get("next_payment_date"), key=f"nextdate_{debt['id']}",
                    )
                    changed = (
                        new_agreement != (debt.get("payment_agreement") or "")
                        or new_next_date != debt.get("next_payment_date")
                    )
                    if changed and st.button("Afspraak opslaan", key=f"save_agreement_{debt['id']}"):
                        db.update_debt(
                            debt["id"], payment_agreement=new_agreement or None, next_payment_date=new_next_date,
                        )
                        st.rerun()

                    st.divider()
                    tab_log, tab_betaling, tab_taken, tab_contact = st.tabs(
                        ["📝 Communicatie", "💶 Betalingen", "✅ Taken", "📇 Contact"]
                    )

                    with tab_log:
                        logs = logs_by_debt.get(debt["id"], [])
                        if logs:
                            for log in logs:
                                wie = f" — *{log['logged_by']}*" if log.get("logged_by") else ""
                                st.write(f"- `{log['date']}` {log['note']}{wie}")
                        else:
                            st.caption("Nog geen notities.")
                        with st.form(f"log_form_{debt['id']}", clear_on_submit=True):
                            note = st.text_input("Nieuwe notitie", key=f"note_{debt['id']}")
                            if st.form_submit_button("Loggen") and note:
                                db.add_debt_log(debt["id"], note, logged_by=current_user)
                                st.rerun()

                    with tab_betaling:
                        payments = payments_by_debt.get(debt["id"], [])
                        if payments:
                            for p in payments:
                                st.write(f"- `{p['date']}` {eur(p['amount'])} betaald — *{p['logged_by']}*")
                        else:
                            st.caption("Nog geen betalingen geregistreerd.")
                        with st.form(f"payment_form_{debt['id']}", clear_on_submit=True):
                            pcol1, pcol2 = st.columns([2, 1])
                            pay_amount = pcol1.number_input("Bedrag", min_value=0.0, step=50.0, key=f"pay_{debt['id']}")
                            pay_date = pcol2.date_input("Datum", value=date.today(), key=f"paydate_{debt['id']}")
                            if st.form_submit_button("Betaling registreren") and pay_amount > 0:
                                db.add_payment(debt["id"], pay_amount, logged_by=current_user, payment_date=pay_date)
                                st.success("Betaling geregistreerd, bedrag automatisch bijgewerkt.")
                                st.rerun()

                    with tab_taken:
                        related_tasks = tasks_by_debt.get(debt["id"], [])
                        if related_tasks:
                            for t in related_tasks:
                                status_icon = "✅" if t["status"] == "Done" else "⬜"
                                due = t["due_date"].strftime("%d-%m") if t["due_date"] else "geen datum"
                                st.write(f"{status_icon} {t['title']} — {t['assigned_to']} ({due})")
                        else:
                            st.caption("Geen taken gekoppeld aan deze schuld.")
                        with st.form(f"task_form_{debt['id']}", clear_on_submit=True):
                            tcol1, tcol2, tcol3 = st.columns(3)
                            task_title = tcol1.text_input("Taak", key=f"tasktitle_{debt['id']}", placeholder=f"Bel {debt['creditor_name']}")
                            task_assignee = tcol2.selectbox("Wie", ASSIGNEES, key=f"taskassignee_{debt['id']}")
                            task_due = tcol3.date_input("Deadline", value=date.today(), key=f"taskdue_{debt['id']}")
                            if st.form_submit_button("Taak toevoegen") and task_title:
                                db.add_task(task_title, task_assignee, current_user, due_date=task_due, related_debt_id=debt["id"])
                                st.rerun()

                    with tab_contact:
                        ccol1, ccol2 = st.columns(2)
                        with ccol1:
                            with st.form(f"contact_form_{debt['id']}"):
                                c_type = st.text_input("Type contact", value=debt.get("contact_type") or "")
                                c_address = st.text_input("Adres", value=debt.get("address") or "")
                                ac1, ac2 = st.columns(2)
                                c_postal = ac1.text_input("Postcode", value=debt.get("postal_code") or "")
                                c_city = ac2.text_input("Plaats", value=debt.get("city") or "")
                                c_phone = st.text_input("Telefoonnummer", value=debt.get("phone") or "")
                                c_email = st.text_input("E-mailadres", value=debt.get("email") or "")
                                if st.form_submit_button("💾 Contactgegevens opslaan"):
                                    db.update_contact(
                                        debt["contact_id"], contact_type=c_type or None,
                                        address=c_address or None, postal_code=c_postal or None,
                                        city=c_city or None, phone=c_phone or None, email=c_email or None,
                                    )
                                    st.rerun()

                        with ccol2:
                            st.markdown("**Snel bericht sturen**")
                            wa_templates = db.get_templates(channel="WhatsApp")
                            mail_templates = db.get_templates(channel="Email")

                            wa_options = {"— vrije tekst —": None}
                            wa_options.update({t["name"]: t for t in wa_templates})
                            wa_choice = st.selectbox("WhatsApp-sjabloon", list(wa_options.keys()), key=f"watpl_{debt['id']}")
                            wa_default = fill_template(wa_options[wa_choice]["body"], debt) if wa_options[wa_choice] else ""
                            wa_text = st.text_area("Bericht", value=wa_default, key=f"watext_{debt['id']}")
                            wa_url = whatsapp_link(debt.get("phone"), wa_text)
                            if wa_url:
                                st.link_button("📱 Open in WhatsApp", wa_url)
                            else:
                                st.caption("Geen telefoonnummer bekend — vul dit links in om WhatsApp te kunnen gebruiken.")

                            st.markdown("---")
                            mail_options = {"— vrije tekst —": None}
                            mail_options.update({t["name"]: t for t in mail_templates})
                            mail_choice = st.selectbox("E-mailsjabloon", list(mail_options.keys()), key=f"mailtpl_{debt['id']}")
                            mail_subject_default = fill_template(mail_options[mail_choice]["subject"], debt) if mail_options[mail_choice] else ""
                            mail_body_default = fill_template(mail_options[mail_choice]["body"], debt) if mail_options[mail_choice] else ""
                            mail_subject = st.text_input("Onderwerp", value=mail_subject_default or "", key=f"mailsub_{debt['id']}")
                            mail_body = st.text_area("Bericht", value=mail_body_default, key=f"mailbody_{debt['id']}")
                            if not debt.get("email"):
                                st.caption("Geen e-mailadres bekend — vul dit links in om te kunnen versturen.")
                            else:
                                if st.button("✉️ Verstuur e-mail", key=f"sendmail_{debt['id']}"):
                                    success, error = emailer.send_email(debt["email"], mail_subject, mail_body)
                                    if success:
                                        db.add_debt_log(
                                            debt["id"], f"E-mail verzonden: '{mail_subject}'", logged_by=current_user
                                        )
                                        st.success(f"E-mail verzonden naar {debt['email']}.")
                                        st.rerun()
                                    else:
                                        st.error(f"Versturen mislukt: {error}")


    # --- Onderdeel: Pipeline & Inkomsten ------------------------------------
    elif sub_page == "📈 Pipeline & Inkomsten":
        st.subheader("📊 Opbrengsten: begroot vs. werkelijk")
        with st.popover("➕ Opbrengstenbron toevoegen"):
            with st.form("add_stream_form", clear_on_submit=True):
                s_name = st.text_input("Naam (bijv. 'ESPN', 'Lezingen bedrijven')")
                s_budget = st.number_input("Begroot bedrag per jaar", min_value=0.0, step=500.0)
                s_year = st.number_input("Jaar", min_value=2020, max_value=2100, value=date.today().year, step=1)
                if st.form_submit_button("Toevoegen") and s_name:
                    db.add_revenue_stream(s_name, s_budget, year=int(s_year))
                    st.rerun()

        overview = db.get_revenue_overview()
        if not overview:
            st.info("Nog geen opbrengstenbronnen toegevoegd.")
        else:
            total_budget = sum(r["budgeted_amount"] for r in overview)
            total_realized = sum(r["realized_amount"] for r in overview)
            overall_pct = (total_realized / total_budget * 100) if total_budget else 0

            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Totaal begroot", eur(total_budget))
            sc2.metric("Totaal gerealiseerd", eur(total_realized))
            sc3.metric("Voortgang", f"{overall_pct:.0f}%")

            odf = pd.DataFrame(overview)
            odf["pct"] = (odf["realized_amount"] / odf["budgeted_amount"] * 100).round(0).fillna(0)
            odf = odf[["name", "budgeted_amount", "realized_amount", "pct"]]
            odf.columns = ["Bron", "Begroot", "Gerealiseerd", "%"]
            st.dataframe(
                odf, use_container_width=True, hide_index=True,
                column_config={
                    "Begroot": st.column_config.NumberColumn(format="€ %.0f"),
                    "Gerealiseerd": st.column_config.NumberColumn(format="€ %.0f"),
                    "%": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
                },
            )

        st.divider()
        col_income, col_pipeline = st.columns(2)

        with col_income:
            st.subheader("Inkomsten")
            with st.popover("➕ Inkomsten registreren"):
                with st.form("add_income_form", clear_on_submit=True):
                    source = st.text_input("Bron")
                    amount = st.number_input("Bedrag", min_value=0.0, step=100.0)
                    streams = db.get_revenue_streams()
                    stream_options = {"— geen koppeling —": None}
                    stream_options.update({s["name"]: s["id"] for s in streams})
                    stream_choice = st.selectbox("Koppelen aan opbrengstenbron (optioneel)", list(stream_options.keys()))
                    if st.form_submit_button("Toevoegen") and source:
                        db.add_income(source, amount, "Gerealiseerd", entered_by=current_user, stream_id=stream_options[stream_choice])
                        st.success("Inkomsten geregistreerd.")
                        st.rerun()

            st.markdown("**Gerealiseerde inkomsten**")
            income_rows = db.get_income()
            if income_rows:
                for i in income_rows:
                    icol1, icol2, icol3 = st.columns([3, 1.3, 0.5])
                    icol1.write(f"{i['date'].strftime('%d-%m-%Y')} — {i['source']}")
                    icol2.write(eur(i["amount"]))
                    if icol3.button("🗑️", key=f"del_income_{i['id']}"):
                        db.delete_income(i["id"])
                        st.rerun()
            else:
                st.info("Nog geen inkomsten geregistreerd.")

        with col_pipeline:
            st.subheader("Pipeline: deals & financiering")
            with st.popover("➕ Deal of financiering toevoegen"):
                with st.form("add_pipeline_form", clear_on_submit=True):
                    deal_type = st.radio("Soort", ["Business", "Financiering/lening"], horizontal=True)
                    company = st.text_input("Bedrijf / partij")
                    p_status = st.selectbox("Fase", PIPELINE_STATUSES)
                    potential_value = st.number_input("Potentiële waarde / leenbedrag", min_value=0.0, step=500.0)
                    next_action = st.text_input("Volgende actie")
                    if st.form_submit_button("Toevoegen") and company:
                        db.add_pipeline(company, p_status, potential_value, next_action, owner=current_user, deal_type=deal_type)
                        st.success("Toegevoegd.")
                        st.rerun()

            pipeline_filter = st.radio("Filter", ["Alle", "Business", "Financiering/lening"], horizontal=True)
            filter_value = None if pipeline_filter == "Alle" else pipeline_filter
            pipeline_rows = [p for p in db.get_pipeline() if p.get("deal_type") != "Business Case"]
            if filter_value:
                pipeline_rows = [p for p in pipeline_rows if p.get("deal_type") == filter_value]

            st.markdown("**Overzicht**")
            if pipeline_rows:
                for item in pipeline_rows:
                    type_icon = "🏦" if item.get("deal_type") == "Financiering/lening" else "🤝"
                    with st.expander(f"{type_icon} {item['company']} — {item['status']} ({eur(item['potential_value'])})"):
                        st.caption(f"Eigenaar: {item.get('owner') or '—'}  ·  Soort: {item.get('deal_type') or 'Business'}")
                        new_p_status = st.selectbox(
                            "Fase bijwerken", PIPELINE_STATUSES,
                            index=PIPELINE_STATUSES.index(item["status"]) if item["status"] in PIPELINE_STATUSES else 0,
                            key=f"pstatus_{item['id']}",
                        )
                        st.caption(f"Volgende actie: {item['next_action'] or '—'}")
                        pc1, pc2 = st.columns(2)
                        if pc1.button("Fase opslaan", key=f"save_pstatus_{item['id']}"):
                            db.update_pipeline(item["id"], status=new_p_status)
                            st.rerun()
                        if pc2.button("🗑️ Verwijderen", key=f"del_pipeline_{item['id']}"):
                            db.delete_pipeline(item["id"])
                            st.rerun()
            else:
                st.info("Nog geen items.")

    # --- Onderdeel: Business Cases (toekomstige projecten) -------------------
    elif sub_page == "🚀 Business Cases":
        st.caption(
            "Toekomstige projecten die nog opgezet moeten worden (bijv. VoetbalCity) — los van lopende "
            "zakendeals. Zodra een case geld gaat opleveren, registreer je dat gewoon als inkomsten."
        )
        with st.popover("➕ Nieuwe business case"):
            with st.form("add_bizcase_form", clear_on_submit=True):
                bc_name = st.text_input("Naam project", placeholder="Bijv. 'VoetbalCity'")
                bc_status = st.selectbox("Fase", ["Idee", "Onderzoek", "Opzetten", "Actief", "Gestopt"])
                bc_value = st.number_input("Verwachte opbrengst", min_value=0.0, step=1000.0)
                bc_next_action = st.text_input("Volgende actie")
                if st.form_submit_button("Toevoegen") and bc_name:
                    db.add_pipeline(bc_name, bc_status, bc_value, bc_next_action, owner=current_user, deal_type="Business Case")
                    st.rerun()

        cases = [p for p in db.get_pipeline() if p.get("deal_type") == "Business Case"]
        if not cases:
            st.info("Nog geen business cases toegevoegd.")
        else:
            for item in cases:
                with st.expander(f"🚀 {item['company']} — {item['status']} (verwacht {eur(item['potential_value'])})"):
                    st.caption(f"Eigenaar: {item.get('owner') or '—'}")
                    new_status = st.selectbox(
                        "Fase bijwerken", ["Idee", "Onderzoek", "Opzetten", "Actief", "Gestopt"],
                        index=["Idee", "Onderzoek", "Opzetten", "Actief", "Gestopt"].index(item["status"])
                        if item["status"] in ["Idee", "Onderzoek", "Opzetten", "Actief", "Gestopt"] else 0,
                        key=f"bcstatus_{item['id']}",
                    )
                    st.caption(f"Volgende actie: {item['next_action'] or '—'}")
                    bc1, bc2 = st.columns(2)
                    if bc1.button("Fase opslaan", key=f"save_bcstatus_{item['id']}"):
                        db.update_pipeline(item["id"], status=new_status)
                        st.rerun()
                    if bc2.button("🗑️ Verwijderen", key=f"del_bc_{item['id']}"):
                        db.delete_pipeline(item["id"])
                        st.rerun()

    # --- Onderdeel: Lopende kosten -------------------------------------------
    elif sub_page == "🧾 Lopende kosten":
        top1, top2 = st.columns([4, 1])
        with top1:
            st.caption("Bedrijfskosten en vergoedingen die (nog) betaald moeten worden — inclusief je eigen fee.")
        with top2:
            with st.popover("➕ Nieuwe kostenpost"):
                with st.form("add_cost_form", clear_on_submit=True):
                    rc_name = st.text_input("Omschrijving", placeholder="Bijv. 'Beheervergoeding Ibrahim'")
                    rc_category = st.text_input("Categorie", placeholder="Bijv. Personeel, Advies, Hosting")
                    rc_amount = st.number_input("Bedrag", min_value=0.0, step=50.0)
                    rc_frequency = st.selectbox("Frequentie", ["Eenmalig", "Maandelijks", "Jaarlijks"])
                    rc_payable_to = st.selectbox("Te betalen aan", ASSIGNEES + ["Extern"])
                    rc_due = st.date_input("Vervaldatum", value=date.today())
                    rc_notes = st.text_area("Toelichting (optioneel)")
                    if st.form_submit_button("Toevoegen") and rc_name:
                        db.add_running_cost(
                            rc_name, rc_amount, current_user, category=rc_category or None,
                            frequency=rc_frequency, payable_to=rc_payable_to, due_date=rc_due, notes=rc_notes or None,
                        )
                        st.rerun()

        filter_status_rc = st.radio("Filter", ["Alle", "Open", "Betaald"], horizontal=True, key="rc_filter")
        status_map = {"Open": "Open", "Betaald": "Betaald", "Alle": None}
        costs = db.get_running_costs(status=status_map[filter_status_rc])

        if not costs:
            st.info("Nog geen lopende kosten geregistreerd.")
        else:
            total_open = sum(c["amount"] for c in costs if c["status"] == "Open")
            st.metric("Totaal openstaand", eur(total_open))
            st.divider()
            for c in costs:
                due = c["due_date"].strftime("%d-%m-%Y") if c["due_date"] else "—"
                label = f"{c['name']} — {eur(c['amount'])} ({c['frequency']}) — {c['status']} — vervalt {due}"
                with st.expander(label):
                    st.caption(f"Categorie: {c.get('category') or '—'}  ·  Te betalen aan: {c.get('payable_to') or '—'}")
                    if c.get("notes"):
                        st.write(c["notes"])
                    cc1, cc2, cc3 = st.columns(3)
                    if c["status"] == "Open":
                        if cc1.button("✅ Markeer als betaald", key=f"paid_rc_{c['id']}"):
                            db.update_running_cost(c["id"], status="Betaald")
                            st.rerun()
                    else:
                        if cc1.button("↩️ Heropenen", key=f"reopen_rc_{c['id']}"):
                            db.update_running_cost(c["id"], status="Open")
                            st.rerun()
                    if cc2.button("🗑️ Verwijderen", key=f"del_rc_{c['id']}"):
                        db.delete_running_cost(c["id"])
                        st.rerun()

    # --- Onderdeel: Privé-uitgaven --------------------------------------------
    elif sub_page == "🏠 Privé-uitgaven":
        top1, top2 = st.columns([4, 1])
        with top1:
            st.caption("Persoonlijk huishoudbudget, los van de bedrijfsschulden en -kosten.")
        with top2:
            with st.popover("➕ Nieuwe uitgave"):
                with st.form("add_expense_form", clear_on_submit=True):
                    pe_category = st.selectbox(
                        "Categorie",
                        ["Wonen", "Verzekeringen", "Levensonderhoud", "Vervoer", "Overig", "Onvoorzien"],
                    )
                    pe_desc = st.text_input("Omschrijving", placeholder="Bijv. 'Huur', 'Ziektekostenverzekering'")
                    pe_amount = st.number_input("Bedrag per maand", min_value=0.0, step=25.0)
                    if st.form_submit_button("Toevoegen") and pe_desc:
                        db.add_private_expense(pe_category, pe_desc, pe_amount, current_user)
                        st.rerun()

        expenses = db.get_private_expenses()
        if not expenses:
            st.info("Nog geen privé-uitgaven geregistreerd.")
        else:
            total_monthly = sum(e["amount_monthly"] for e in expenses)
            total_yearly = sum(e["amount_yearly"] for e in expenses)
            mc1, mc2 = st.columns(2)
            mc1.metric("Totaal per maand", eur(total_monthly))
            mc2.metric("Totaal per jaar", eur(total_yearly))
            st.divider()

            categories = sorted(set(e["category"] for e in expenses))
            for cat in categories:
                cat_expenses = [e for e in expenses if e["category"] == cat]
                cat_total = sum(e["amount_monthly"] for e in cat_expenses)
                st.markdown(f"**{cat}** — {eur(cat_total)}/mnd")
                for e in cat_expenses:
                    ecol1, ecol2, ecol3 = st.columns([3, 1.3, 0.5])
                    ecol1.write(e["description"])
                    new_amount = ecol2.number_input(
                        "Bedrag/mnd", value=float(e["amount_monthly"]), step=10.0,
                        key=f"pe_amt_{e['id']}", label_visibility="collapsed",
                    )
                    if new_amount != e["amount_monthly"]:
                        db.update_private_expense(e["id"], amount_monthly=new_amount)
                        st.rerun()
                    if ecol3.button("🗑️", key=f"del_pe_{e['id']}"):
                        db.delete_private_expense(e["id"])
                        st.rerun()
                st.divider()

    # --- Onderdeel: Liquiditeit ------------------------------------------------
    elif sub_page == "💧 Liquiditeitsbegroting":
        st.caption(
            "Van boven naar beneden: omzet, dan bedrijfskosten, dan privé-uitgaven — wat overblijft is "
            "je aflossingscapaciteit. Schulden staan hier bewust buiten; de verdeling over schuldeisers "
            "bepaal je zelf, via 'Betaling registreren' bij de betreffende schuldeiser."
        )

        view_mode = st.radio("Weergave", ["Per week", "Per maand"], horizontal=True, key="cashflow_view")
        start = date(2026, 7, 1)
        n_periods = 12 if view_mode == "Per week" else 6

        # Periodes opbouwen vanaf 1 juli 2026
        periods = []
        if view_mode == "Per week":
            year, week, _ = start.isocalendar()
            cursor = start - timedelta(days=start.weekday())  # begin van de week (maandag)
            for _ in range(n_periods):
                p_end = cursor + timedelta(days=6)
                y, w, _ = cursor.isocalendar()
                periods.append({"start": cursor, "end": p_end, "label": f"Week {w} — {y}", "month": cursor.month})
                cursor = cursor + timedelta(days=7)
        else:
            y, m = start.year, start.month
            for _ in range(n_periods):
                p_start = date(y, m, 1)
                p_end = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1) - timedelta(days=1)
                periods.append({"start": p_start, "end": p_end, "label": p_start.strftime("%B %Y"), "month": m})
                m += 1
                if m > 12:
                    m = 1
                    y += 1

        income_rows = db.get_income()
        cost_rows = db.get_running_costs()
        privé_total_monthly = sum(e["amount_monthly"] for e in db.get_private_expenses())
        privé_per_period = privé_total_monthly if view_mode == "Per maand" else privé_total_monthly * 12 / 52

        rows = []
        for p in periods:
            omzet = float(sum(r["amount"] for r in income_rows if p["start"] <= r["date"] <= p["end"]))

            kosten = 0.0
            for c in cost_rows:
                if not c["due_date"] or c["due_date"] > p["end"]:
                    continue
                if c["frequency"] == "Eenmalig":
                    if p["start"] <= c["due_date"] <= p["end"]:
                        kosten += float(c["amount"])
                elif c["frequency"] == "Maandelijks":
                    if view_mode == "Per maand":
                        kosten += float(c["amount"])
                    else:
                        kosten += float(c["amount"]) * 12 / 52
                elif c["frequency"] == "Jaarlijks":
                    if p["start"].month == c["due_date"].month and view_mode == "Per maand":
                        kosten += float(c["amount"])

            resultaat = omzet - kosten
            aflossing = resultaat - privé_per_period
            rows.append({
                "Periode": p["label"], "Omzet": omzet, "Bedrijfskosten": -kosten,
                "Resultaat": resultaat, "Privé-uitgaven": -privé_per_period,
                "Aflossingscapaciteit": aflossing,
            })

        cdf = pd.DataFrame(rows)
        st.dataframe(
            cdf, use_container_width=True, hide_index=True,
            column_config={c: st.column_config.NumberColumn(format="€ %.0f") for c in
                            ["Omzet", "Bedrijfskosten", "Resultaat", "Privé-uitgaven", "Aflossingscapaciteit"]},
        )

        totaal_aflossing = cdf["Aflossingscapaciteit"].sum()
        st.metric(f"Totale aflossingscapaciteit ({n_periods} {'weken' if view_mode == 'Per week' else 'maanden'})", eur(totaal_aflossing))
        st.caption(
            "Omzet = alle geregistreerde inkomsten in die periode. Bedrijfskosten = lopende kosten "
            "(incl. salaris), waarbij 'Maandelijks' automatisch elke periode terugkomt vanaf de ingevulde "
            "vervaldatum. Privé-uitgaven worden gelijkmatig verdeeld over de periodes (bij weekweergave: "
            "maandbedrag × 12 ÷ 52)."
        )

# ===========================================================================
# PAGINA: BEHEER (berichtsjablonen, later ook overige instellingen)
# ===========================================================================
elif page == "⚙️ Beheer":
    st.title("Beheer")
    st.subheader("✉️ Berichtsjablonen")
    st.caption(
        "Standaardteksten voor WhatsApp en e-mail. Gebruik {naam} in de tekst — dat wordt automatisch "
        "vervangen door de naam van de schuldeiser wanneer je een sjabloon gebruikt bij Schulden → Contact."
    )

    with st.popover("➕ Nieuw sjabloon"):
        with st.form("add_template_form", clear_on_submit=True):
            t_name = st.text_input("Naam van het sjabloon")
            t_channel = st.selectbox("Kanaal", ["WhatsApp", "Email"])
            t_subject = st.text_input("Onderwerp (alleen voor e-mail)")
            t_body = st.text_area("Berichttekst", placeholder="Beste {naam}, ...")
            if st.form_submit_button("Opslaan") and t_name and t_body:
                db.add_template(t_name, t_channel, t_body, current_user, subject=t_subject or None)
                st.rerun()

    tab_wa, tab_mail = st.tabs(["📱 WhatsApp-sjablonen", "✉️ E-mailsjablonen"])

    with tab_wa:
        templates = db.get_templates(channel="WhatsApp")
        if not templates:
            st.info("Nog geen WhatsApp-sjablonen.")
        for t in templates:
            with st.expander(t["name"]):
                st.write(t["body"])
                if st.button("🗑️ Verwijderen", key=f"deltpl_wa_{t['id']}"):
                    db.delete_template(t["id"])
                    st.rerun()

    with tab_mail:
        templates = db.get_templates(channel="Email")
        if not templates:
            st.info("Nog geen e-mailsjablonen.")
        for t in templates:
            with st.expander(t["name"]):
                st.caption(f"Onderwerp: {t['subject'] or '—'}")
                st.write(t["body"])
                if st.button("🗑️ Verwijderen", key=f"deltpl_mail_{t['id']}"):
                    db.delete_template(t["id"])
                    st.rerun()
