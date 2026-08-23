from benchmarks.structural_benchmark import datasets, bench_one


def test_structural_benchmark_workloads_roundtrip():
    for name, data in datasets(16 * 1024):
        result = bench_one(name, data)
        assert result.original == len(data)
        assert result.structural > 0
        assert result.de2 > 0
        assert result.structural_de2 > 0


def test_structural_pipeline_can_improve_structured_numeric_data():
    result = bench_one("numeric-delta", datasets(16 * 1024)[0][1])
    assert result.structural < result.original
    assert result.structural_de2 <= result.de2
