"""
Generic-noun / non-skill rejection pre-filter (spec §17: "framework" is
context, not a technical skill). Ported from the proven C# EntityClassifier +
SkillNormalizer heuristics mined from the prior system -- a defense-in-depth
layer applied BEFORE catalog matching, so obviously-non-technical candidates
never waste a fuzzy/semantic match attempt (and can't accidentally score a
deceptive fuzzy-match hit against an unrelated real skill name).

The actual hard guarantee against inventing skills like "framework" is
architectural (a candidate is only ever accepted if it resolves to a real
TechnicalSkill catalog row) -- this filter is a cheap, fast rejection of the
obvious cases before that resolution is even attempted.
"""
import re

_GENERIC_WORDS = {w.lower() for w in [
    "framework", "platform", "application", "system", "solution", "technology",
    "project", "experience", "development", "years", "year", "tool", "tools",
    "environment", "process", "scope", "responsibilities", "responsibility",
    "requirements", "team", "teams", "department", "company", "organization",
    "module", "modules", "concept", "concepts", "methodology", "approach",
]}

_NON_TECHNICAL_WORDS = {w.lower() for w in [
    "Hindi", "Urdu", "Telugu", "Tamil", "English", "French", "Spanish", "German",
    "Kannada", "Malayalam", "Bengali", "Marathi", "Arabic", "Mandarin", "Japanese",
    "Communication", "Punctual", "Hardworking", "Dedication", "Team Player",
    "Active Mindset", "Leadership", "Management", "Problem Solving", "Curious",
    "Fast Learner", "Self Motivated", "Adaptability", "Time Management",
]}

_INSTITUTION_STEMS = {w.lower() for w in [
    "Bachelor", "Master", "Diploma", "University", "College", "Institute",
    "Campus", "School", "Academy", "Associate", "Degree", "GPA", "CGPA",
]}

_LOCATIONS = {w.lower() for w in [
    "India", "USA", "U.S.A", "United States", "United Kingdom", "UK", "Canada",
    "Australia", "Germany", "France", "Singapore", "China", "Japan", "Ireland",
    "Netherlands", "Spain", "Italy", "Mexico", "Brazil",
    "Coimbatore", "Chennai", "Bangalore", "Bengaluru", "Mumbai", "Delhi",
    "Hyderabad", "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Kochi", "Noida",
    "Gurgaon", "Gurugram",
    "New York", "San Francisco", "Seattle", "Austin", "Boston", "Chicago",
    "London", "Toronto", "Vancouver", "Berlin", "Dubai", "Sydney", "Melbourne",
    "Tamil Nadu", "Karnataka", "Maharashtra", "Kerala", "Telangana",
    "Uttar Pradesh", "Gujarat", "West Bengal", "Punjab", "Rajasthan",
]}

_HOBBIES = {w.lower() for w in [
    "Cooking", "Baking", "Badminton", "Cricket", "Football", "Soccer",
    "Basketball", "Tennis", "Table Tennis", "Volleyball", "Chess", "Reading",
    "Painting", "Drawing", "Sketching", "Photography", "Traveling",
    "Travelling", "Gaming", "Video Games", "Yoga", "Swimming", "Dancing",
    "Singing", "Gardening", "Hiking", "Trekking", "Cycling", "Running",
    "Fishing", "Camping", "Meditation", "Playing Guitar", "Playing Piano",
    "Watching Movies", "Listening to Music", "Blogging", "Origami",
    "Calligraphy", "Stamp Collecting", "Bird Watching",
]}

_FRAGMENT_STOP_WORDS = {
    "including", "include", "includes", "with", "and", "the", "for", "of", "in",
    "on", "as", "by", "to", "from", "without", "within", "prioritizing",
    "responsible", "responsibilities", "conducting", "preparing", "performing",
}

_ALL_DIGITS = re.compile(r"^\d+$")
_DATE_LIKE = re.compile(r"\b(19|20)\d{2}\b")


def is_plausible_skill_candidate(text: str) -> bool:
    """Fast pre-filter -- True means "worth attempting catalog matching",
    False means "reject outright, do not spend a match attempt". This is
    intentionally permissive (a real skill must never be rejected here); the
    catalog-match step is what ultimately decides identity."""
    if not text or not text.strip():
        return False
    trimmed = text.strip()
    lowered = trimmed.lower()

    if lowered in _GENERIC_WORDS or lowered in _NON_TECHNICAL_WORDS:
        return False
    if lowered in _LOCATIONS or lowered in _HOBBIES:
        return False
    if len(trimmed) < 2 or len(trimmed) > 60:
        return False
    if _ALL_DIGITS.match(trimmed):
        return False
    if _DATE_LIKE.search(trimmed) and len(trimmed.split()) <= 2:
        return False
    if trimmed.count("(") != trimmed.count(")"):
        return False

    words = [w for w in trimmed.split(" ") if w]
    if any(w.strip("(),.").lower() in _INSTITUTION_STEMS for w in words):
        return False
    if any(w.strip("(),.").lower() in _FRAGMENT_STOP_WORDS for w in words):
        return False
    if len(words) >= 2 and trimmed == trimmed.upper() and any(c.isalpha() for c in trimmed):
        return False  # reads as a leaked section header, e.g. "EDUCATIONAL QUALIFICATION"
    if len(words) > 6:
        return False  # reads as a sentence/description fragment

    return True
