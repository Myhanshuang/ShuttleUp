from shuttleup.activities.workflow_routes import coverage_count
from shuttleup.models import ActivityPlan, Booking


def make_booking(court,start,end): return Booking(activity_id="a",plan_id="p",venue_id="v",court_ids=[court],starts_at=start,ends_at=end,booker_participant_id="x",status="confirmed")


def test_multiple_bookings_only_confirm_continuous_named_courts():
    plan=ActivityPlan(id="p",activity_id="a",plan_no=1,starts_at=100,ends_at=300,venue_id="v",court_ids=["c1"],roster_participant_ids=[],candidate_fingerprint="f",snapshot={},selected_by="u")
    assert coverage_count([make_booking("c1",100,200),make_booking("c1",200,300)],plan)==1
    assert coverage_count([make_booking("c1",100,200),make_booking("c2",200,300)],plan)==0

