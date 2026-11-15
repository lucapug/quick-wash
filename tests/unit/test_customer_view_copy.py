"""The copy tables of the customer frontend (issue #20): the language split, as data.

Pure data only: no repository, no clock object, no mock — the seam discipline (docs/spec.md, Testing
Decisions). What the pages render is asserted at the HTTP seam, in
tests/integration/test_customer_view_coverage.py; what this file pins is the one place the strings live and
the one reading of the issue's language rule, so the implementation and the tests cannot drift.

The rule, in the words the tests use: AC1 asks for an Italian interface and the issue's Decision overrides
it to English; AC4 asks for a reason for every gap "using the vocabulary from issue #10", and that vocabulary
is the seven pinned tokens of `src/availability.py::REASONS`. Both hold at once, because the token is the
vocabulary and the sentence around it is the copy — and the copy is English. `REASON_COPY` therefore has
exactly one entry per token, and no other word. The as-is domain copy the tests pin in the API's language is
not in `strings()`, which is what makes the split checkable rather than a preference.
"""

from pathlib import Path

from src import app as backend
from src import availability, entitlements, views

ROOT = Path(__file__).resolve().parents[2]


def test_the_reason_copy_covers_exactly_the_vocabulary_issue_10_fixes():
    assert sorted(views.REASON_COPY) == sorted(availability.REASONS)
    # A token with no sentence would render as a bare word; a sentence for a token outside the vocabulary
    # would answer with a word the seam never answers with. Both are the drift the reviewer checked.
    assert all(views.REASON_COPY[word] for word in availability.REASONS)
    assert set(views.EXTRA_REASON_COPY) == {"in_the_past"}            # a cause the public window cannot name
    assert not set(views.EXTRA_REASON_COPY) & set(availability.REASONS)


def test_every_customer_facing_string_follows_the_decision_and_is_english():
    assert views.LANGUAGE == "en" and views.DOCUMENTATION_LANGUAGE == "en"
    offenders = {key: views.italian_markers(value) for key, value in views.strings().items()}
    assert not {key: found for key, found in offenders.items() if found}, offenders
    # The as-is domain copy is outside the table: it is the pinned decision's own language, shown as-is.
    assert entitlements.missing_session()["message"] not in views.strings().values()


def test_a_gap_line_shows_the_token_and_the_english_sentence_that_reads_it():
    line = views.slot_line({"start": "10:00", "reason": "all_machines_busy"}, "quick")
    assert 'data-reason="all_machines_busy"' in line                  # the pinned token, unchanged
    assert views.REASON_COPY["all_machines_busy"] in line             # and the sentence that reads it
    offered = views.slot_line({"start": "10:15", "reason": None}, "quick", earliest=True)
    assert 'data-action="take" data-type="quick" data-start="10:15"' in offered   # AC3: one tap
    assert 'data-earliest="1"' in offered


def test_the_two_report_actions_are_the_copy_the_shell_renders_and_the_kinds_the_seam_accepts():
    assert [kind for kind, _ in views.REPORT_ACTIONS] == sorted(backend.REPORT_KINDS)
    assert views.REPORT_ACTIONS == (("fault", views.COPY["report_fault"]),
                                    ("occupied", views.COPY["report_occupied"]))
    assert not [views.italian_markers(label) for _, label in views.REPORT_ACTIONS if views.italian_markers(label)]


def test_every_string_in_the_table_is_a_string_the_page_renders():
    """Dead copy is the drift the review flagged: an entry no page shows is a second vocabulary."""
    source = (ROOT / "src" / "views.py").read_text(encoding="utf-8")
    dead = [key for key in views.COPY
            if f'copy("{key}"' not in source and f'COPY["{key}"]' not in source
            and not (key.startswith("title_") and 'COPY[f"title_' in source)]
    assert not dead, dead
    # The renderer reaches the table before anything else: a gap line is the token plus its sentence.
    assert 'REASON_COPY.get(word)' in source


def test_the_booking_screen_states_the_four_things_in_the_order_ac6_lists_them():
    order = [views.copy(key, machine="M7", start="10:00", end="10:30", tokens=3)
             for key in ("machine", "start", "expected_end", "tokens")]
    facts = views.book_facts("M7", "10:00", "10:30", 3)
    positions = [facts.index(views.esc(line)) for line in order]
    assert positions == sorted(positions), (positions, facts)
