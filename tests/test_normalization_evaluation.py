from trzip.normalization_evaluation import evaluate_holdout, write_holdout_report


def test_frozen_holdout_meets_declared_targets_and_writes_errors(tmp_path):
    report = evaluate_holdout()
    assert report["evaluated_count"] >= 20
    assert report["name_accuracy"] >= 0.85
    assert report["category_accuracy"] >= 0.90
    assert report["dangerous_false_links"] == 0
    assert isinstance(report["errors"], list)

    output = tmp_path / "normalization.json"
    written = write_holdout_report(output)
    assert output.exists()
    assert written == report
