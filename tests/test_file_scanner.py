from ingestion.file_scanner import scan_source_files


def make_tree(root, files):
    for relative in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n", encoding="utf-8")


def test_scanner_keeps_supported_source_and_skips_excluded_folders(tmp_path):
    make_tree(tmp_path, [
        "superset/app.py",
        "docs/admin_docs/install.mdx",
        "docs/developer_docs_versioned_docs/version-6.0.0/install.mdx",
        "docs/user_docs_versioned_sidebars/version-6.0.0.md",
        "superset-frontend/node_modules/lib/index.ts",
        "superset/__pycache__/app.py",
        "assets/logo.png",
    ])

    found = sorted(p.relative_to(tmp_path).as_posix() for p in scan_source_files(tmp_path))

    assert found == ["docs/admin_docs/install.mdx", "superset/app.py"]


def test_folders_above_the_corpus_root_do_not_trigger_exclusions(tmp_path):
    root = tmp_path / "build" / "corpus"
    make_tree(root, ["superset/app.py"])

    assert [p.name for p in scan_source_files(root)] == ["app.py"]
