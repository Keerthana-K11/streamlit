import os
import requests
import streamlit as st
from dotenv import load_dotenv, dotenv_values

# ---------------------------------------------------------------------------
# Config & Auth
# ---------------------------------------------------------------------------

load_dotenv(override=True)
env_vars = dotenv_values(".env")

BASE_URL = env_vars.get("API_BASE_URL") or os.environ.get("API_BASE_URL", "http://localhost:8000")
FIREBASE_API_KEY = env_vars.get("FIREBASE_API_KEY") or os.environ.get("FIREBASE_API_KEY", "")
FIREBASE_EMAIL = env_vars.get("FIREBASE_EMAIL") or os.environ.get("FIREBASE_EMAIL", "")
FIREBASE_PASSWORD = env_vars.get("FIREBASE_PASSWORD") or os.environ.get("FIREBASE_PASSWORD", "")


@st.cache_data(ttl=3600)
def get_auth_token():
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    payload = {"email": FIREBASE_EMAIL, "password": FIREBASE_PASSWORD, "returnSecureToken": True}
    resp = requests.post(url, json=payload)
    if resp.status_code == 200:
        return resp.json()["idToken"]
    return None


def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def search_destinations(query: str, token: str):
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v1/destinations",
            params={"search": query, "limit": 10},
            headers=auth_headers(token),
            timeout=10,
        )
        if resp.status_code == 200:
            try:
                data = resp.json()
            except requests.exceptions.JSONDecodeError:
                return []
            # handle both list and {data: [...]} shapes
            if isinstance(data, list):
                return data
            
            payload = data.get("data", {})
            if isinstance(payload, dict) and "destinations" in payload:
                return payload["destinations"]
                
            return data.get("data", data.get("results", []))
    except Exception:
        pass
    return []


def fetch_landmarks(destination_id: str, token: str):
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v1/places",
            params={"destination_id": destination_id, "limit": 50, "is_landmark": "true", "sort": "trending"},
            headers=auth_headers(token),
            timeout=10,
        )
        if resp.status_code == 200:
            try:
                data = resp.json()
            except requests.exceptions.JSONDecodeError:
                return []
            if isinstance(data, list):
                return data
            
            payload = data.get("data", {})
            if isinstance(payload, dict) and "places" in payload:
                return payload["places"]
                
            return data.get("data", data.get("results", []))
    except Exception:
        pass
    return []


def generate_itinerary(payload: dict, token: str):
    resp = requests.post(
        f"{BASE_URL}/api/v1/itineraries/generate/v1",
        json=payload,
        headers=auth_headers(token),
        timeout=300,
    )
    try:
        result = resp.json()
    except requests.exceptions.JSONDecodeError:
        result = {"error": "Invalid JSON response", "raw": resp.text}
    return resp.status_code, result


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

STEPS = ["Destination", "Group", "Days & Date", "Budget", "Interests", "Landmarks", "AI Model", "Generate"]

def login_with_firebase(email: str, password: str):
    """Authenticate user with Firebase and return token"""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("idToken")
            if token:
                # Store in session for persistence across refreshes
                st.session_state.auth_token_storage = {"email": email, "token": token}
            return token, email
        else:
            error_data = resp.json()
            error_msg = error_data.get("error", {}).get("message", "Login failed")
            return None, error_msg
    except Exception as e:
        return None, str(e)


def restore_auth_if_exists():
    """Restore authentication from session storage if it exists"""
    if "auth_token_storage" not in st.session_state:
        return False

    stored = st.session_state.auth_token_storage
    if not stored:
        return False

    email = stored.get("email")
    token = stored.get("token")

    if email and token:
        st.session_state.authenticated = True
        st.session_state.token = token
        st.session_state.user_email = email
        return True
    return False


def init_state():
    defaults = {
        "authenticated": False,
        "step": 0,
        "token": None,
        "user_email": None,
        "auth_token_storage": None,
        "destination_id": None,
        "destination_name": None,
        "group_type": None,
        "people_count": 1,
        "days": 2,
        "start_date": None,
        "budget_tier": None,
        "budget": None,
        "interests": [],
        "landmarks": [],          # all landmarks for destination
        "pre_selected_ids": [],   # user chosen landmark ids
        "llm_provider": "groq",
        "llm_model": "llama-3.1-8b-instant",
        "itinerary": None,
        "generation_metrics": None,
        "error": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def go_to(step: int):
    st.session_state.step = step
    st.session_state.error = None

def back():
    if st.session_state.step > 0:
        st.session_state.step -= 1
        st.session_state.error = None


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def show_progress():
    current = st.session_state.step
    total = len(STEPS) - 1  # last step is result view
    st.write(f"Step {current + 1} of {total + 1}  —  **{STEPS[current]}**")
    st.progress((current) / (total))
    st.write("")


def show_error():
    if st.session_state.error:
        st.error(st.session_state.error)


def back_button(label="Back"):
    if st.session_state.step > 0:
        st.button(label, on_click=back, key=f"back_{st.session_state.step}")


# ---------------------------------------------------------------------------
# Login UI
# ---------------------------------------------------------------------------

def step_login():
    st.subheader("Welcome to Itinerary Planner")
    st.write("")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.write("Please login to continue")
        st.write("")

        email = st.text_input("Email", placeholder="your@email.com", key="login_email")
        password = st.text_input("Password", type="password", placeholder="Enter password", key="login_password")
        st.write("")

        if st.button("Login", use_container_width=True):
            if not email or not password:
                st.session_state.error = "Please enter both email and password."
                st.rerun()

            with st.spinner("Logging in..."):
                token, result = login_with_firebase(email, password)

            if token:
                st.session_state.authenticated = True
                st.session_state.token = token
                st.session_state.user_email = email
                st.session_state.error = None
                st.rerun()
            else:
                st.session_state.error = f"Login failed: {result}"
                st.rerun()

    show_error()



# ---------------------------------------------------------------------------
# Step renderers
# ---------------------------------------------------------------------------

def step_destination(token):
    st.subheader("Where do you want to go?")
    st.write("")

    query = st.text_input("Search destination", placeholder="e.g. Auroville, Goa, Coorg")

    if query and len(query) >= 2:
        with st.spinner("Searching..."):
            results = search_destinations(query, token)

        if results:
            options = {r["name"]: r["id"] for r in results}
            choice = st.radio("Select a destination", list(options.keys()))
            if st.button("Continue"):
                st.session_state.destination_id = options[choice]
                st.session_state.destination_name = choice
                go_to(1)
                st.rerun()
        else:
            # fallback: let user paste destination_id manually
            st.caption("No results from API. Enter destination ID manually below.")
            dest_id = st.text_input("Destination ID")
            dest_name = st.text_input("Destination name (for display)")
            if st.button("Continue") and dest_id:
                st.session_state.destination_id = dest_id
                st.session_state.destination_name = dest_name or dest_id
                go_to(1)
                st.rerun()
    else:
        st.caption("Type at least 2 characters to search.")

    show_error()


def step_group():
    st.subheader("Who is travelling?")
    st.write("")

    options = ["solo", "couple", "family", "friends"]
    labels = {"solo": "Solo", "couple": "Couple", "family": "Family", "friends": "Friends"}

    choice = st.radio(
        "Group type",
        options,
        format_func=lambda x: labels[x],
        index=options.index(st.session_state.group_type) if st.session_state.group_type in options else 0,
    )

    people_count = 1
    if choice == "solo":
        people_count = 1
    elif choice == "couple":
        people_count = 2
    elif choice in ("family", "friends"):
        people_count = st.number_input("Number of people", min_value=2, max_value=20, value=4, step=1)

    col1, col2 = st.columns([1, 1])
    with col1:
        back_button()
    with col2:
        if st.button("Continue"):
            st.session_state.group_type = choice
            st.session_state.people_count = int(people_count)
            go_to(2)
            st.rerun()

    show_error()


def step_days_date():
    st.subheader("When and how long?")
    st.write("")

    import datetime

    days = st.number_input(
        "Number of days",
        min_value=1,
        max_value=14,
        value=st.session_state.days,
        step=1,
    )

    min_date = datetime.date.today()
    start_date = st.date_input(
        "Start date",
        value=st.session_state.start_date or min_date,
        min_value=min_date,
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        back_button()
    with col2:
        if st.button("Continue"):
            st.session_state.days = int(days)
            st.session_state.start_date = start_date
            go_to(3)
            st.rerun()

    show_error()


def step_budget():
    st.subheader("What is your budget?")
    st.write("")

    tiers = {
        "backpacker": "Backpacker  (under 5,000)",
        "mid-range": "Mid-range   (5,000 - 10,000)",
        "luxury": "Luxury      (above 25,000)",
    }

    choice = st.radio(
        "Budget tier",
        list(tiers.keys()),
        format_func=lambda x: tiers[x],
        index=list(tiers.keys()).index(st.session_state.budget_tier) if st.session_state.budget_tier in tiers else 1,
    )

    budget_value = None
    if choice == "backpacker":
        budget_value = st.slider("Custom amount (optional)", 1000, 5000, 3000, step=500)
    elif choice == "mid-range":
        budget_value = st.slider("Custom amount (optional)", 5000, 10000, 7500, step=500)
    elif choice == "luxury":
        budget_value = st.slider("Custom amount (optional)", 25000, 100000, 50000, step=5000)

    col1, col2 = st.columns([1, 1])
    with col1:
        back_button()
    with col2:
        if st.button("Continue"):
            st.session_state.budget_tier = choice
            st.session_state.budget = budget_value
            go_to(4)
            st.rerun()

    show_error()


def step_interests():
    st.subheader("What kind of experiences are you looking for?")
    st.write("")

    all_interests = ["Adventure", "Culture", "Historic", "Food", "Nature", "Spiritual", "Shopping", "Cafes", "Popular"]

    selected = st.multiselect(
        "Select one or more interests",
        all_interests,
        default=st.session_state.interests if st.session_state.interests else [],
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        back_button()
    with col2:
        if st.button("Continue"):
            if not selected:
                st.session_state.error = "Please select at least one interest."
                st.rerun()
            else:
                st.session_state.interests = selected
                go_to(5)
                st.rerun()

    show_error()


def step_landmarks(token):
    st.subheader("Add landmarks to your itinerary")
    st.write("This step is optional. Select places you definitely want to visit.")
    st.caption(f"Destination: {st.session_state.destination_name}  |  Days: {st.session_state.days}")
    st.write("")

    # Fetch landmarks once and cache in session
    if not st.session_state.landmarks:
        with st.spinner("Loading places for this destination..."):
            landmarks = fetch_landmarks(st.session_state.destination_id, token)
            st.session_state.landmarks = landmarks

    landmarks = st.session_state.landmarks

    max_picks = st.session_state.days * 2  # rough cap

    if not landmarks:
        st.info("No landmark data available for this destination from the API. You can skip this step.")
    else:
        st.caption(f"You can pre-select up to {max_picks} landmarks ({st.session_state.days} days x 2).")
        st.write("")

        # Group by category if available
        by_cat = {}
        for lm in landmarks:
            cat = lm.get("category", "general").replace("-", " ").title()
            by_cat.setdefault(cat, []).append(lm)

        selected_ids = list(st.session_state.pre_selected_ids)

        for cat, places in by_cat.items():
            st.write(f"**{cat}**")
            for place in places:
                pid = place["id"]
                name = place.get("name", pid)
                rating = place.get("rating")
                label = name if not rating else f"{name}  ({rating})"
                checked = pid in selected_ids
                if st.checkbox(label, value=checked, key=f"lm_{pid}"):
                    if pid not in selected_ids:
                        selected_ids.append(pid)
                else:
                    if pid in selected_ids:
                        selected_ids.remove(pid)

        if len(selected_ids) > max_picks:
            st.warning(f"You have selected {len(selected_ids)} landmarks. Consider reducing to {max_picks} for a comfortable trip.")

        st.session_state.pre_selected_ids = selected_ids

    st.write("")
    col1, col2 = st.columns([1, 1])
    with col1:
        back_button()
    with col2:
        if st.button("Generate Itinerary"):
            go_to(6)
            st.rerun()

    show_error()


def step_model_selection():
    st.subheader("Choose AI Model")
    st.write("")
    st.caption("Select which AI model you'd like to use for generating your itinerary.")
    st.write("")

    providers = ["groq", "gemini"]
    models = {
        "groq": ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "openai/gpt-oss-120b", "groq/compound"],
        "gemini": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview", "gemini-3.1-flash-lite"]
    }

    if "llm_provider" not in st.session_state:
        st.session_state.llm_provider = "groq"
    if "llm_model" not in st.session_state:
        st.session_state.llm_model = "llama-3.1-8b-instant"

    col1, col2 = st.columns(2)
    with col1:
        provider = st.selectbox(
            "AI Provider",
            providers,
            index=providers.index(st.session_state.llm_provider),
            key="llm_provider_select"
        )
    with col2:
        available_models = models.get(provider, [])
        model = st.selectbox(
            "Model",
            available_models,
            index=available_models.index(st.session_state.llm_model) if st.session_state.llm_model in available_models else 0,
            key="llm_model_select"
        )

    st.write("")
    st.info("ℹ️ Changing models will affect the quality and cost of your itinerary. Choose wisely before proceeding.")
    st.write("")

    col1, col2 = st.columns([1, 1])
    with col1:
        back_button()
    with col2:
        if st.button("Continue to Generate"):
            st.session_state.llm_provider = provider
            st.session_state.llm_model = model
            go_to(7)
            st.rerun()

    show_error()


def step_generate(token):
    st.subheader("Generating your itinerary")
    st.write("")

    # Summary card
    st.write("**Your choices**")
    st.write(f"Destination: {st.session_state.destination_name}")
    st.write(f"Group: {st.session_state.group_type.title()},  {st.session_state.get('people_count', 1)} people")
    st.write(f"Days: {st.session_state.days}  |  Start: {st.session_state.start_date}")
    st.write(f"Budget: {st.session_state.budget_tier}")
    st.write(f"Interests: {', '.join(st.session_state.interests)}")
    st.write(f"AI Model: {st.session_state.llm_provider.title()} - {st.session_state.llm_model}")
    if st.session_state.pre_selected_ids:
        st.write(f"Pre-selected landmarks: {len(st.session_state.pre_selected_ids)}")
    st.write("")

    if st.session_state.itinerary is None:
        with st.spinner("Generating your personalized itinerary... this may take up to 30 seconds."):
            payload = {
                "destination_id": st.session_state.destination_id,
                "days": st.session_state.days,
                "people_count": st.session_state.get("people_count", 1),
                "group_type": st.session_state.group_type,
                "start_date": str(st.session_state.start_date),
                "budget_tier": st.session_state.budget_tier,
                "interests": st.session_state.interests,
                "pre_selected_ids": st.session_state.pre_selected_ids,
                "llm_provider": st.session_state.llm_provider,
                "llm_model": st.session_state.llm_model,
            }
            if st.session_state.get("budget"):
                payload["budget"] = st.session_state.budget

            status, result = generate_itinerary(payload, token)

        if status in (200, 201):
            if "error" in result:
                st.session_state.error = f"API returned invalid JSON: {result.get('raw', 'empty response')}"
                st.error(st.session_state.error)
                col1, _ = st.columns([1, 3])
                with col1:
                    back_button("Go back and adjust")
                return
            data = result.get("data", result)
            st.session_state.itinerary = data
            # Extract metrics from root level or from data
            st.session_state.generation_metrics = result.get("generation_metrics") or data.get("generation_metrics")
            st.rerun()
        else:
            error_msg = result.get("message", result.get("error", result))
            st.session_state.error = f"API error {status}: {error_msg}"
            st.error(st.session_state.error)
            col1, _ = st.columns([1, 3])
            with col1:
                back_button("Go back and adjust")
            return

    # Render itinerary
    itin = st.session_state.itinerary
    if itin:
        render_itinerary(itin)

    # Display generation metrics if available
    if st.session_state.generation_metrics:
        st.write("")
        st.divider()
        st.write("**📊 Generation Metrics**")
        metrics = st.session_state.generation_metrics

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            input_tokens = metrics.get("input_tokens")
            st.metric("Input Tokens", f"{input_tokens:,}" if isinstance(input_tokens, int) else input_tokens or "N/A")
        with col2:
            output_tokens = metrics.get("output_tokens")
            st.metric("Output Tokens", f"{output_tokens:,}" if isinstance(output_tokens, int) else output_tokens or "N/A")
        with col3:
            time_taken = metrics.get("time_taken_secs")
            st.metric("Time Taken", f"{time_taken}s" if time_taken else "N/A")
        with col4:
            cost = metrics.get("cost_inr")
            st.metric("Cost (INR)", f"₹{cost:.4f}" if isinstance(cost, (int, float)) else cost or "N/A")
    else:
        # Debug: show if metrics exist but are None
        if st.session_state.itinerary:
            st.write("")
            st.caption("ℹ️ Generation metrics not available in response")

    st.write("")
    st.divider()
    if st.button("Start over"):
        # Clear only itinerary-related state, preserve authentication
        keys_to_clear = [
            "step", "destination_id", "destination_name", "group_type",
            "days", "start_date", "budget_tier", "interests", "landmarks",
            "pre_selected_ids", "itinerary", "generation_metrics", "error",
            "people_count", "llm_provider", "llm_model", "budget"
        ]
        for k in keys_to_clear:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()


def render_itinerary(itin: dict):
    st.success("Itinerary ready")
    st.write("")
    st.write(f"### {itin.get('title', 'Your Itinerary')}")
    st.write(f"Destination: **{itin.get('destination')}**  |  {itin.get('total_days')} days  |  {itin.get('total_people')} people")
    st.write("")

    for day in itin.get("days", []):
        day_num = day.get("day_number")
        date = day.get("date", "")
        theme = day.get("theme", "")
        notes = day.get("notes", "")

        st.write(f"---")
        st.write(f"#### Day {day_num}  —  {date}")
        if theme:
            st.write(f"*{theme}*")
        if notes and notes != theme:
            with st.expander("Day notes"):
                st.write(notes)
        st.write("")

        for item in day.get("items", []):
            place = item.get("place") or {}
            name = item.get("custom_name") or place.get("name", "Unknown place")
            start = item.get("start_time", "")
            end = item.get("end_time", "")
            time_str = f"{start} - {end}" if start and end else start or ""
            item_notes = item.get("notes", "")
            category = place.get("sub_category", place.get("category", "")).replace("-", " ").title()
            rating = place.get("rating")

            col_time, col_info = st.columns([1, 4])
            with col_time:
                st.write(time_str)
            with col_info:
                rating_str = f"  {rating}" if rating else ""
                st.write(f"**{name}**{rating_str}")
                if category:
                    st.caption(category)
                if item_notes:
                    st.write(item_notes)
            st.write("")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Itinerary Planner", layout="centered")
    st.title("Itinerary Planner")

    init_state()

    # Try to restore auth if user was logged in
    if not st.session_state.authenticated:
        restore_auth_if_exists()

    # Show logout button if authenticated
    if st.session_state.authenticated:
        col1, col2, col3 = st.columns([4, 1, 1])
        with col3:
            if st.button("Logout", use_container_width=True):
                st.session_state.authenticated = False
                st.session_state.token = None
                st.session_state.user_email = None
                st.session_state.auth_token_storage = None
                for k in list(st.session_state.keys()):
                    if k not in ["authenticated", "token", "user_email", "auth_token_storage", "error"]:
                        del st.session_state[k]
                st.rerun()
        with col2:
            st.caption(st.session_state.user_email)

    st.write("")

    # Show login page if not authenticated
    if not st.session_state.authenticated:
        step_login()
        return

    token = st.session_state.token
    step = st.session_state.step

    # Progress bar only for planning steps (not result)
    if step < len(STEPS) - 1:
        show_progress()

    if step == 0:
        step_destination(token)
    elif step == 1:
        step_group()
    elif step == 2:
        step_days_date()
    elif step == 3:
        step_budget()
    elif step == 4:
        step_interests()
    elif step == 5:
        step_landmarks(token)
    elif step == 6:
        step_model_selection()
    elif step == 7:
        step_generate(token)


if __name__ == "__main__":
    main()