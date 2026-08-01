from evaluation.source_readiness import scan_sources


class Ready:
    def readiness(self): return {"status": "READY", "read_only": True}


def test_scanner_distinguishes_ready_and_unconfigured_sources():
    result = scan_sources({"downstream": Ready(), "member": None})
    assert result["first_milestone_met"] is True
    assert result["source_readiness"]["member"]["status"] == "NOT_CONFIGURED"
