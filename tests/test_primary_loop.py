import json
from nucsys_agent.workflow import run_agent
from nucsys_agent.export_validation import validate_alchemy_export

def test_primary_loop_export_valid():
    res = run_agent("design the primary coolant system for a 300 MWth nuclear reactor, minimize pumping power")
    issues = validate_alchemy_export(res.alchemy_db)
    assert not [i for i in issues if i.level == "error"]

    # Basic structural checks
    assert "Building" in res.alchemy_db
    assert "Building 2" in res.alchemy_db
    assert len(res.alchemy_db["Building"]["parts"]) > 0
    assert len(res.alchemy_db["Building 2"]["parts"]) > 0
