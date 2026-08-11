"""Temporary-directory tests for safe adapter and instruction installation."""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import stat
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from scripts import install_adapters


class InstallAdaptersTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.destinations = install_adapters.Destinations(
            project=self.root / "project",
            skills=self.root / "skills",
            instructions=self.root / "instructions",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def options(self, mode: str = "copy", **overrides: object) -> install_adapters.InstallOptions:
        values = {
            "mode": mode,
            "destinations": self.destinations,
            "targets": ("claude_code", "codex"),
            "workspace_trust": "pending",
            "server_approval": "pending",
            "activation": "inactive",
        }
        values.update(overrides)
        return install_adapters.InstallOptions(**values)

    def canonical(self, name: str = "canonical") -> Path:
        canonical = self.root / name
        (canonical / "skills" / "one").mkdir(parents=True)
        (canonical / "agents").mkdir(parents=True)
        (canonical / "skills" / "one" / "keep.md").write_text(
            "keep\n", encoding="utf-8"
        )
        (canonical / "agents" / "worker.md").write_text(
            "worker\n", encoding="utf-8"
        )
        return canonical

    def test_repository_project_metadata_is_recovery_identity_only(self) -> None:
        metadata = tomllib.loads(
            (install_adapters.ROOT / ".zabin" / "project.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {"project_id": "prj_0000019ff1c0d556QOqHpnzw"}, metadata
        )

    def test_clean_copy_install_merges_all_bundles_with_restrictive_metadata(self) -> None:
        report = install_adapters.install(self.options())
        self.assertEqual("installed", report.installation)
        self.assertTrue((self.destinations.skills / "conductor" / "SKILL.md").is_file())
        self.assertTrue((self.destinations.instructions / "implementor.md").is_file())
        self.assertTrue((self.destinations.project / ".mcp.json").is_file())
        self.assertTrue((self.destinations.project / ".codex" / "config.toml").is_file())
        manifest_path = self.destinations.project / ".zabin" / "installer-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(install_adapters.INSTALLER_ID, manifest["installer"])
        self.assertTrue(manifest["provenance"].startswith("sha256:"))
        self.assertEqual(0o600, stat.S_IMODE(manifest_path.stat().st_mode))
        self.assertEqual(
            0o644,
            stat.S_IMODE((self.destinations.skills / "conductor" / "SKILL.md").stat().st_mode),
        )

    def test_structural_merge_preserves_unrelated_native_configuration(self) -> None:
        project = self.destinations.project
        (project / ".claude").mkdir(parents=True)
        (project / ".codex").mkdir(parents=True)
        (project / ".mcp.json").write_text(
            json.dumps({"native": {"secret_value": "do-not-log"}, "mcpServers": {"foreign": {"url": "https://foreign.invalid"}}}),
            encoding="utf-8",
        )
        (project / ".claude" / "settings.json").write_text(
            json.dumps({"theme": "dark", "permissions": {"allow": ["Read"], "ask": [], "deny": []}, "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "native"}]}]}}),
            encoding="utf-8",
        )
        (project / ".codex" / "config.toml").write_text(
            'model = "native"\n'
            'mixed = [1, "two", { nested = { flag = true }, values = [1, { k = "v" }] }, [3, "four"]]\n'
            'inline = { child = { enabled = true }, list = [{ x = 1 }, 2] }\n'
            '[mcp_servers.foreign]\nurl = "https://foreign.invalid"\n',
            encoding="utf-8",
        )
        native_codex = tomllib.loads(
            (project / ".codex" / "config.toml").read_text(encoding="utf-8")
        )
        install_adapters.install(self.options())

        mcp = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual("do-not-log", mcp["native"]["secret_value"])
        self.assertIn("foreign", mcp["mcpServers"])
        settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual("dark", settings["theme"])
        self.assertIn("Read", settings["permissions"]["allow"])
        self.assertEqual("native", settings["hooks"]["SessionStart"][0]["hooks"][0]["command"])
        codex = tomllib.loads((project / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual("native", codex["model"])
        self.assertEqual(native_codex["mixed"], codex["mixed"])
        self.assertEqual(native_codex["inline"], codex["inline"])
        self.assertIn("foreign", codex["mcp_servers"])

    def test_deterministic_toml_serializer_preserves_supported_toml_value_types(self) -> None:
        source = tomllib.loads(
            'date = 2026-08-12\n'
            'instant = 2026-08-12T01:02:03Z\n'
            'mixed = [1, "two", true, { nested = { values = [1, { k = "v" }] } }]\n'
            'inline = { child = { enabled = true }, values = [[1, "two"], { x = 3 }] }\n'
            'unicode = "snowman ☃ and face 😀"\n'
            'control = "escaped\\u007f"\n'
        )
        rendered = install_adapters._dump_toml(source)
        self.assertEqual(source, tomllib.loads(rendered.decode("utf-8")))
        self.assertEqual(rendered, install_adapters._dump_toml(source))

    def test_idempotent_rerun_and_check_make_no_changes(self) -> None:
        install_adapters.install(self.options())
        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.destinations.project.rglob("*")
            if path.is_file()
        }
        rerun = install_adapters.install(self.options())
        checked = install_adapters.install(self.options("check"))
        self.assertEqual("unchanged", rerun.installation)
        self.assertEqual((), rerun.changes)
        self.assertEqual("verified", checked.installation)
        self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before})

    def test_check_and_dry_run_never_write(self) -> None:
        dry = install_adapters.install(self.options("dry-run"))
        check = install_adapters.install(self.options("check"))
        self.assertEqual("planned", dry.installation)
        self.assertEqual("drift", check.installation)
        self.assertFalse(self.destinations.project.exists())
        self.assertFalse(self.destinations.skills.exists())
        self.assertFalse(self.destinations.instructions.exists())

    def test_installer_owned_update_is_allowed_but_user_modification_fails(self) -> None:
        install_adapters.install(self.options())
        mcp_path = self.destinations.project / ".mcp.json"
        mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
        mcp["unrelated"] = True
        mcp_path.write_text(json.dumps(mcp), encoding="utf-8")
        updated = install_adapters.install(self.options())
        self.assertEqual("installed", updated.installation)
        self.assertTrue(json.loads(mcp_path.read_text(encoding="utf-8"))["unrelated"])

        mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
        mcp["mcpServers"]["zabin"]["headers"]["Authorization"] = "literal-secret"
        mcp_path.write_text(json.dumps(mcp), encoding="utf-8")
        with self.assertRaises(install_adapters.CollisionError) as caught:
            install_adapters.install(self.options())
        message = str(caught.exception)
        self.assertIn("server ID collision", message)
        self.assertNotIn("literal-secret", message)
        self.assertIn("<redacted>", message)

    def test_owned_server_and_tool_removal_requires_matching_fingerprints(self) -> None:
        destination = self.root / "native.json"
        old_server = {"url": "https://old.invalid"}
        server_entry = {"owned": {"server:old": install_adapters._canonical_digest(old_server)}}
        merged, owned = install_adapters._merge_servers(
            {"old": old_server, "foreign": {"url": "https://foreign.invalid"}},
            {},
            server_entry,
            destination,
            "mcpServers",
        )
        self.assertEqual({"foreign": {"url": "https://foreign.invalid"}}, merged)
        self.assertEqual({}, owned)

        rule = "mcp__zabin__removed_tool"
        current = {
            "permissions": {"allow": [rule, "Read"], "ask": [], "deny": []},
            "hooks": {"SessionStart": []},
        }
        desired_hook = {"hooks": [{"command": "new", "type": "command"}]}
        desired = {
            "permissions": {"allow": [], "ask": [], "deny": []},
            "hooks": {"SessionStart": [desired_hook]},
        }
        entry = {
            "owned": {
                f"tool:{rule}": install_adapters._canonical_digest({"bucket": "allow", "rule": rule})
            }
        }
        merged_settings, _ = install_adapters._merge_claude_settings(
            current, desired, entry, destination
        )
        self.assertEqual(["Read"], merged_settings["permissions"]["allow"])

    def test_foreign_server_id_url_and_tool_rule_collisions_fail_closed(self) -> None:
        project = self.destinations.project
        project.mkdir()
        (project / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"zabin": {"url": "https://foreign.invalid"}}}), encoding="utf-8"
        )
        with self.assertRaisesRegex(install_adapters.CollisionError, "server ID collision"):
            install_adapters.install(self.options(targets=("claude_code",)))

        (project / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"foreign": {"url": "http://127.0.0.1:50052/mcp"}}}), encoding="utf-8"
        )
        with self.assertRaisesRegex(install_adapters.CollisionError, "server URL collision"):
            install_adapters.install(self.options(targets=("claude_code",)))

        (project / ".mcp.json").unlink()
        (project / ".claude").mkdir()
        (project / ".claude" / "settings.json").write_text(
            json.dumps({"permissions": {"allow": ["mcp__zabin__get_task"], "ask": [], "deny": []}}), encoding="utf-8"
        )
        with self.assertRaisesRegex(install_adapters.CollisionError, "tool rule collision"):
            install_adapters.install(self.options(targets=("claude_code",)))

    def test_redacted_diff_uses_field_allowlist_not_token_patterns(self) -> None:
        current = {"url": "https://safe.invalid", "innocent_name": "sensitive-value", "headers": {"Authorization": "not-token-shaped"}}
        expected = {"url": "https://expected.invalid", "innocent_name": "different", "headers": {"Authorization": "other"}}
        diff = install_adapters.structural_diff(current, expected)
        serialized = json.dumps(diff)
        self.assertIn("https://safe.invalid", serialized)
        self.assertIn("<redacted-field>", serialized)
        self.assertNotIn("sensitive-value", serialized)
        self.assertNotIn("not-token-shaped", serialized)

    def test_tampered_ownership_fingerprint_is_rejected_before_install(self) -> None:
        install_adapters.install(self.options())
        manifest_path = self.destinations.project / ".zabin" / "installer-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        first = next(iter(manifest["entries"].values()))
        first["checksum"] = "not-a-cryptographic-fingerprint"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(install_adapters.InstallError, "entry is invalid"):
            install_adapters.install(self.options())

    def test_symlink_mode_links_assets_but_keeps_generated_config_regular(self) -> None:
        report = install_adapters.install(self.options("symlink"))
        self.assertEqual("installed", report.installation)
        skill = self.destinations.skills / "conductor" / "SKILL.md"
        instruction = self.destinations.instructions / "implementor.md"
        self.assertTrue(skill.is_symlink())
        self.assertTrue(instruction.is_symlink())
        self.assertTrue((self.destinations.project / ".mcp.json").is_file())
        self.assertFalse((self.destinations.project / ".mcp.json").is_symlink())
        self.assertEqual("unchanged", install_adapters.install(self.options("symlink")).installation)
        self.assertEqual("verified", install_adapters.install(self.options("check")).installation)

    def test_symlink_checksum_and_provenance_follow_target_content(self) -> None:
        canonical = self.root / "canonical"
        (canonical / "skills" / "one").mkdir(parents=True)
        (canonical / "agents").mkdir(parents=True)
        skill_source = canonical / "skills" / "one" / "SKILL.md"
        skill_source.write_text("version one\n", encoding="utf-8")
        (canonical / "agents" / "worker.md").write_text("worker\n", encoding="utf-8")
        with mock.patch.object(install_adapters, "ROOT", canonical):
            installed = install_adapters.install(self.options("symlink"))
            skill_destination = self.destinations.skills / "one" / "SKILL.md"
            old_checksum = installed.checksums[os.fspath(skill_destination)]
            old_provenance = installed.provenance
            skill_source.write_text("version two\n", encoding="utf-8")
            checked = install_adapters.install(self.options("check"))
        self.assertEqual("drift", checked.installation)
        self.assertIn(os.fspath(skill_destination), checked.changes)
        self.assertNotEqual(old_checksum, checked.checksums[os.fspath(skill_destination)])
        self.assertNotEqual(old_provenance, checked.provenance)

    def test_removed_file_drifts_then_reconciles_in_copy_and_symlink_modes(self) -> None:
        for mode in ("copy", "symlink"):
            with self.subTest(mode=mode):
                canonical = self.canonical(f"canonical-removed-{mode}")
                source = canonical / "skills" / "one" / "obsolete.md"
                source.write_text("obsolete\n", encoding="utf-8")
                destinations = install_adapters.Destinations(
                    self.root / f"project-{mode}",
                    self.root / f"skills-{mode}",
                    self.root / f"instructions-{mode}",
                )
                options = self.options(mode, destinations=destinations)
                destination = destinations.skills / "one" / "obsolete.md"
                with mock.patch.object(install_adapters, "ROOT", canonical):
                    install_adapters.install(options)
                    source.unlink()
                    checked = install_adapters.install(
                        self.options("check", destinations=destinations)
                    )
                    self.assertEqual("drift", checked.installation)
                    self.assertIn(os.fspath(destination), checked.changes)
                    self.assertTrue(destination.exists() or destination.is_symlink())
                    installed = install_adapters.install(options)
                    self.assertFalse(destination.exists() or destination.is_symlink())
                    self.assertTrue(
                        any(Path(path).parent == destination.parent for path in installed.backups)
                    )
                    self.assertEqual(
                        "verified",
                        install_adapters.install(
                            self.options("check", destinations=destinations)
                        ).installation,
                    )

    def test_removed_owned_tree_uses_directory_tombstone_and_rollback(self) -> None:
        for mode in ("copy", "symlink"):
            with self.subTest(mode=mode):
                canonical = self.canonical(f"canonical-tree-{mode}")
                tree = canonical / "skills" / "old"
                (tree / "nested").mkdir(parents=True)
                (tree / "a.md").write_text("a\n", encoding="utf-8")
                (tree / "nested" / "b.md").write_text("b\n", encoding="utf-8")
                destinations = install_adapters.Destinations(
                    self.root / f"tree-project-{mode}",
                    self.root / f"tree-skills-{mode}",
                    self.root / f"tree-instructions-{mode}",
                )
                options = self.options(mode, destinations=destinations)
                installed_tree = destinations.skills / "old"
                with mock.patch.object(install_adapters, "ROOT", canonical):
                    install_adapters.install(options)
                    (tree / "nested" / "b.md").unlink()
                    (tree / "nested").rmdir()
                    (tree / "a.md").unlink()
                    tree.rmdir()
                    report = install_adapters.install(options)
                    self.assertFalse(installed_tree.exists())
                    backups = [Path(path) for path in report.backups]
                    tree_backups = [path for path in backups if path.parent == installed_tree.parent]
                    self.assertEqual(1, len(tree_backups))
                    self.assertTrue(tree_backups[0].is_dir())
                    self.assertEqual(
                        "verified",
                        install_adapters.install(
                            self.options("check", destinations=destinations)
                        ).installation,
                    )

    def test_stale_tree_with_unrelated_file_removes_only_owned_leaves(self) -> None:
        canonical = self.canonical("canonical-partial-tree")
        tree = canonical / "skills" / "old"
        tree.mkdir()
        source = tree / "owned.md"
        source.write_text("owned\n", encoding="utf-8")
        installed_tree = self.destinations.skills / "old"
        with mock.patch.object(install_adapters, "ROOT", canonical):
            install_adapters.install(self.options())
            (installed_tree / "user.md").write_text("user\n", encoding="utf-8")
            source.unlink()
            tree.rmdir()
            install_adapters.install(self.options())
            self.assertFalse((installed_tree / "owned.md").exists())
            self.assertEqual(
                "user\n", (installed_tree / "user.md").read_text(encoding="utf-8")
            )

    def test_missing_stale_asset_keeps_check_in_drift_until_manifest_reconciles(self) -> None:
        canonical = self.canonical("canonical-missing-stale")
        source = canonical / "skills" / "one" / "obsolete.md"
        source.write_text("obsolete\n", encoding="utf-8")
        destination = self.destinations.skills / "one" / "obsolete.md"
        with mock.patch.object(install_adapters, "ROOT", canonical):
            install_adapters.install(self.options())
            source.unlink()
            destination.unlink()
            checked = install_adapters.install(self.options("check"))
            self.assertEqual("drift", checked.installation)
            self.assertIn(os.fspath(destination), checked.changes)
            install_adapters.install(self.options())
            self.assertEqual(
                "verified", install_adapters.install(self.options("check")).installation
            )

    def test_missing_stale_asset_reappearance_aborts_manifest_reconciliation(self) -> None:
        canonical = self.canonical("canonical-reappearing-stale")
        source = canonical / "skills" / "one" / "obsolete.md"
        source.write_text("obsolete\n", encoding="utf-8")
        destination = self.destinations.skills / "one" / "obsolete.md"
        manifest_path = self.destinations.project / ".zabin" / "installer-manifest.json"
        with mock.patch.object(install_adapters, "ROOT", canonical):
            install_adapters.install(self.options())
            manifest_before = manifest_path.read_bytes()
            source.unlink()
            destination.unlink()
            real_replace = os.replace

            def recreate_before_manifest(
                source_path: os.PathLike[str], destination_path: os.PathLike[str]
            ) -> None:
                if str(source_path).endswith(".tmp") and Path(destination_path) == manifest_path:
                    destination.write_text("user appeared\n", encoding="utf-8")
                real_replace(source_path, destination_path)

            with mock.patch(
                "scripts.install_adapters.os.replace",
                side_effect=recreate_before_manifest,
            ):
                with self.assertRaisesRegex(
                    install_adapters.InstallError, "post-install verification failed"
                ):
                    install_adapters.install(self.options())
            self.assertEqual("user appeared\n", destination.read_text(encoding="utf-8"))
            self.assertEqual(manifest_before, manifest_path.read_bytes())

    def test_asset_rename_removes_old_and_installs_new_atomically(self) -> None:
        canonical = self.canonical("canonical-rename")
        old_source = canonical / "skills" / "one" / "old.md"
        new_source = canonical / "skills" / "one" / "new.md"
        old_source.write_text("renamed\n", encoding="utf-8")
        with mock.patch.object(install_adapters, "ROOT", canonical):
            install_adapters.install(self.options())
            old_source.rename(new_source)
            report = install_adapters.install(self.options())
            old_destination = self.destinations.skills / "one" / "old.md"
            new_destination = self.destinations.skills / "one" / "new.md"
            self.assertFalse(old_destination.exists())
            self.assertEqual("renamed\n", new_destination.read_text(encoding="utf-8"))
            manifest = json.loads(
                (self.destinations.project / ".zabin" / "installer-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            destinations = {entry["destination"] for entry in manifest["entries"].values()}
            self.assertNotIn(os.fspath(old_destination), destinations)
            self.assertIn(os.fspath(new_destination), destinations)
            self.assertTrue(
                any(Path(path).parent == old_destination.parent for path in report.backups)
            )

    def test_user_modified_or_retargeted_stale_asset_is_never_deleted(self) -> None:
        for mode in ("copy", "symlink"):
            with self.subTest(mode=mode):
                canonical = self.canonical(f"canonical-refusal-{mode}")
                source = canonical / "skills" / "one" / "obsolete.md"
                source.write_text("owned\n", encoding="utf-8")
                destinations = install_adapters.Destinations(
                    self.root / f"refusal-project-{mode}",
                    self.root / f"refusal-skills-{mode}",
                    self.root / f"refusal-instructions-{mode}",
                )
                options = self.options(mode, destinations=destinations)
                destination = destinations.skills / "one" / "obsolete.md"
                with mock.patch.object(install_adapters, "ROOT", canonical):
                    install_adapters.install(options)
                    source.unlink()
                    if mode == "copy":
                        destination.write_text("user modified\n", encoding="utf-8")
                    else:
                        destination.unlink()
                        foreign = canonical / "foreign.md"
                        foreign.write_text("foreign\n", encoding="utf-8")
                        destination.symlink_to(foreign)
                    with self.assertRaises(install_adapters.CollisionError):
                        install_adapters.install(options)
                    self.assertTrue(destination.exists() or destination.is_symlink())
                    manifest = json.loads(
                        (destinations.project / ".zabin" / "installer-manifest.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertIn(install_adapters._manifest_key(destination), manifest["entries"])

    def test_stale_tree_is_restored_when_later_transaction_step_fails(self) -> None:
        canonical = self.canonical("canonical-stale-rollback")
        tree = canonical / "skills" / "old"
        tree.mkdir()
        source = tree / "owned.md"
        source.write_text("owned\n", encoding="utf-8")
        installed_tree = self.destinations.skills / "old"
        with mock.patch.object(install_adapters, "ROOT", canonical):
            install_adapters.install(self.options())
            source.unlink()
            tree.rmdir()
            manifest_path = self.destinations.project / ".zabin" / "installer-manifest.json"
            manifest_before = manifest_path.read_bytes()
            real_replace = os.replace

            def fail_manifest_install(
                source_path: os.PathLike[str], destination_path: os.PathLike[str]
            ) -> None:
                if str(source_path).endswith(".tmp") and Path(destination_path) == manifest_path:
                    raise OSError(5, "injected manifest failure")
                real_replace(source_path, destination_path)

            with mock.patch(
                "scripts.install_adapters.os.replace", side_effect=fail_manifest_install
            ):
                with self.assertRaisesRegex(install_adapters.InstallError, "transaction failed"):
                    install_adapters.install(self.options())
            self.assertTrue(installed_tree.is_dir())
            self.assertEqual("owned\n", (installed_tree / "owned.md").read_text(encoding="utf-8"))
            self.assertEqual(manifest_before, manifest_path.read_bytes())

    def test_stale_file_and_symlink_tombstones_roll_back_on_manifest_failure(self) -> None:
        for mode in ("copy", "symlink"):
            with self.subTest(mode=mode):
                canonical = self.canonical(f"canonical-file-rollback-{mode}")
                source = canonical / "skills" / "one" / "obsolete.md"
                source.write_text("owned\n", encoding="utf-8")
                destinations = install_adapters.Destinations(
                    self.root / f"file-rollback-project-{mode}",
                    self.root / f"file-rollback-skills-{mode}",
                    self.root / f"file-rollback-instructions-{mode}",
                )
                options = self.options(mode, destinations=destinations)
                destination = destinations.skills / "one" / "obsolete.md"
                manifest_path = destinations.project / ".zabin" / "installer-manifest.json"
                with mock.patch.object(install_adapters, "ROOT", canonical):
                    install_adapters.install(options)
                    manifest_before = manifest_path.read_bytes()
                    source.unlink()
                    real_replace = os.replace

                    def fail_manifest_install(
                        source_path: os.PathLike[str], destination_path: os.PathLike[str]
                    ) -> None:
                        if str(source_path).endswith(".tmp") and Path(destination_path) == manifest_path:
                            raise OSError(5, "injected manifest failure")
                        real_replace(source_path, destination_path)

                    with mock.patch(
                        "scripts.install_adapters.os.replace",
                        side_effect=fail_manifest_install,
                    ):
                        with self.assertRaisesRegex(
                            install_adapters.InstallError, "transaction failed"
                        ):
                            install_adapters.install(options)
                    self.assertTrue(destination.exists() or destination.is_symlink())
                    self.assertEqual(manifest_before, manifest_path.read_bytes())

    def test_rename_rolls_back_old_and_new_destinations_together(self) -> None:
        canonical = self.canonical("canonical-rename-rollback")
        old_source = canonical / "skills" / "one" / "old.md"
        new_source = canonical / "skills" / "one" / "new.md"
        old_source.write_text("owned\n", encoding="utf-8")
        old_destination = self.destinations.skills / "one" / "old.md"
        new_destination = self.destinations.skills / "one" / "new.md"
        manifest_path = self.destinations.project / ".zabin" / "installer-manifest.json"
        with mock.patch.object(install_adapters, "ROOT", canonical):
            install_adapters.install(self.options())
            manifest_before = manifest_path.read_bytes()
            old_source.rename(new_source)
            real_replace = os.replace

            def fail_manifest_install(
                source_path: os.PathLike[str], destination_path: os.PathLike[str]
            ) -> None:
                if str(source_path).endswith(".tmp") and Path(destination_path) == manifest_path:
                    raise OSError(5, "injected manifest failure")
                real_replace(source_path, destination_path)

            with mock.patch(
                "scripts.install_adapters.os.replace", side_effect=fail_manifest_install
            ):
                with self.assertRaisesRegex(install_adapters.InstallError, "transaction failed"):
                    install_adapters.install(self.options())
            self.assertEqual("owned\n", old_destination.read_text(encoding="utf-8"))
            self.assertFalse(new_destination.exists())
            self.assertEqual(manifest_before, manifest_path.read_bytes())

    def test_unsafe_destination_symlink_is_rejected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        project_link = self.root / "project"
        project_link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(install_adapters.InstallError, "unsafe symlink"):
            install_adapters.install(self.options())
        self.assertEqual([], list(outside.iterdir()))

    def test_path_traversal_and_source_overlap_are_rejected(self) -> None:
        traversal = install_adapters.Destinations(
            project=self.root / "safe" / ".." / "project",
            skills=self.root / "skills",
            instructions=self.root / "instructions",
        )
        with self.assertRaisesRegex(install_adapters.InstallError, "path traversal"):
            install_adapters.install(self.options(destinations=traversal))

        overlap = install_adapters.Destinations(
            project=self.root / "project",
            skills=install_adapters.ROOT / "skills",
            instructions=self.root / "instructions",
        )
        with self.assertRaisesRegex(install_adapters.InstallError, "overlaps its canonical source"):
            install_adapters.install(self.options(destinations=overlap))

    def test_transaction_rolls_back_and_retains_backup_on_successful_update(self) -> None:
        install_adapters.install(self.options())
        settings_path = self.destinations.project / ".claude" / "settings.json"
        original_settings = settings_path.read_bytes()
        settings = json.loads(original_settings)
        settings["unrelated"] = "new"
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        real_replace = os.replace
        replacements = 0

        def fail_during_install(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
            nonlocal replacements
            if str(source).endswith(".tmp"):
                replacements += 1
                if replacements == 2:
                    raise OSError(5, "injected failure")
            real_replace(source, destination)

        with mock.patch("scripts.install_adapters.os.replace", side_effect=fail_during_install):
            with self.assertRaisesRegex(install_adapters.InstallError, "transaction failed"):
                install_adapters.install(self.options())
        self.assertEqual(json.dumps(settings).encode(), settings_path.read_bytes())

        installed = install_adapters.install(self.options())
        self.assertEqual("installed", installed.installation)
        self.assertTrue(installed.backups)
        self.assertTrue(all(Path(path).exists() for path in installed.backups))

    def test_destination_local_backups_avoid_cross_filesystem_renames(self) -> None:
        install_adapters.install(self.options())
        real_replace = os.replace

        def reject_cross_parent(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
            if Path(source).parent != Path(destination).parent:
                raise OSError(errno.EXDEV, "simulated cross-device rename")
            real_replace(source, destination)

        with mock.patch("scripts.install_adapters.os.replace", side_effect=reject_cross_parent):
            report = install_adapters.install(self.options("symlink"))
        self.assertEqual("installed", report.installation)
        self.assertTrue(report.backups)
        self.assertTrue(all(Path(path).exists() for path in report.backups))
        self.assertTrue(
            any(Path(path).parent == self.destinations.skills / "conductor" for path in report.backups)
        )
        self.assertTrue(
            any(Path(path).parent == self.destinations.instructions for path in report.backups)
        )

    def test_destination_and_symlink_source_races_fail_before_replacement(self) -> None:
        changes, _ = install_adapters.plan_install(self.options())
        raced = changes[0]
        raced.destination.parent.mkdir(parents=True, exist_ok=True)
        raced.destination.write_text("appeared after preflight", encoding="utf-8")
        with self.assertRaisesRegex(install_adapters.InstallError, "changed after preflight"):
            install_adapters._atomic_apply(changes)

        canonical = self.root / "canonical-race"
        (canonical / "skills" / "one").mkdir(parents=True)
        (canonical / "agents").mkdir(parents=True)
        source = canonical / "skills" / "one" / "SKILL.md"
        source.write_text("before\n", encoding="utf-8")
        (canonical / "agents" / "worker.md").write_text("worker\n", encoding="utf-8")
        fresh_destinations = install_adapters.Destinations(
            self.root / "race-project", self.root / "race-skills", self.root / "race-instructions"
        )
        with mock.patch.object(install_adapters, "ROOT", canonical):
            link_changes, _ = install_adapters.plan_install(
                self.options("symlink", destinations=fresh_destinations)
            )
            source.write_text("after\n", encoding="utf-8")
            with self.assertRaisesRegex(install_adapters.InstallError, "symlink source changed"):
                install_adapters._atomic_apply(link_changes)

    def test_reporting_keeps_install_trust_approval_and_activation_distinct(self) -> None:
        report = install_adapters.install(
            self.options(
                "dry-run",
                workspace_trust="pending",
                server_approval="approved",
                activation="inactive",
            )
        ).as_dict()
        self.assertEqual("planned", report["installation"])
        self.assertEqual("pending", report["workspace_trust"])
        self.assertEqual("approved", report["server_approval"])
        self.assertEqual("inactive", report["activation"])
        self.assertIn("does not grant workspace trust", report["state_notice"])
        self.assertIn("hostile local actor", report["race_notice"])

    def test_ordinary_install_never_reads_or_writes_codex_requirements(self) -> None:
        requirements = self.destinations.project / "requirements.toml"
        requirements.parent.mkdir(parents=True)
        requirements.write_text("admin_secret = \"leave-me\"\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"ZABIN_MCP_TOKEN": "must-not-read"}, clear=True):
            install_adapters.install(self.options())
        self.assertEqual('admin_secret = "leave-me"\n', requirements.read_text(encoding="utf-8"))
        manifest = (self.destinations.project / ".zabin" / "installer-manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("requirements.toml", manifest)
        self.assertNotIn("must-not-read", manifest)

    def test_cli_requires_every_destination_and_check_uses_distinct_exit_code(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            install_adapters.main(["--mode", "dry-run"])
        argv = [
            "--mode", "check",
            "--project-destination", os.fspath(self.destinations.project),
            "--skills-destination", os.fspath(self.destinations.skills),
            "--instructions-destination", os.fspath(self.destinations.instructions),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, install_adapters.main(argv))


if __name__ == "__main__":
    unittest.main()
