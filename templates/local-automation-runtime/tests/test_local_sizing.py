from __future__ import annotations

import base64
import copy
import importlib.machinery
import importlib.util
import json
import sys
import unittest
from unittest import mock
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

loader = importlib.machinery.SourceFileLoader("atlas_local_sizing_test", str(ROOT / "atlas_local_sizing.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
sizing = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = sizing
loader.exec_module(sizing)


def make_context(
    *,
    paths: list[str] | None = None,
    criteria: list[str] | None = None,
    purposes: dict[str, str] | None = None,
    interfaces: list[str] | None = None,
    questions: list[str] | None = None,
    flags: list[str] | None = None,
) -> dict:
    return {
        "write_scope": paths if paths is not None else ["src/acceptance.py"],
        "acceptance_criteria": criteria if criteria is not None else [
            "The local operation records a clear acceptance result."
        ],
        "local_execution_v1": {
            "policy_id": "local-luna-unit-v1",
            "role_purposes": purposes if purposes is not None else {"implementation": "implementation"},
            "changed_interfaces": interfaces if interfaces is not None else [],
            "unresolved_questions": questions if questions is not None else [],
            "complexity_flags": flags if flags is not None else [],
        },
    }


# Frozen canonical provider.project contexts, embedded so tests need no task artifacts.
_STALE_REVIEWED_CONTEXTS_ZLIB_B64 = (
    "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"
    "3P5/ptC//htt6j4y"
)
_REVIEWED_CONTEXTS_ZLIB_B64 = (
    "eNrtWm1v3DYS/ivEfkoPK2u93nUSG3dAnBZFDsWlaNBPh0LgUtQuY4lUScr2Ntf/fs8MKe3azeHSg4G74hYFUq9IDofz8swzlD7N"
    "3lzMrj7Noomtnl3Nvv6xWJwXi6V4c3El3tmovZWtaIw1UYveuztTay/unb/F/2Qte8yYzWdbJ1usftf1re60jcLZdi/iTovGu1+0"
    "hTgR3OCVFgNEicZ5MW0V3LhB6xR2I+nYSwft73QQIbp+LrCvhZL7OWmxxWAQ0taQprSP0ti4PxMfZDSh2Qt9p/1eBOV6XQuplO6j"
    "xDyhPDbxxtnrSbwwtta9tiRdeH1n9D3LlW2LlXGAOsY22musL8fzl7WMciODLr1WjjfbQHWYJJzBGPe0TcXbz67+PosaVpFRh5KP"
    "V8ghug6aOlv4AWfqdCljK0Mht1CicF7tdIheRkeW/YLVGIyB/61YUMUzqzD0OKEJzp/1+9lP85l+0GqglZXXvYO7yp0bNy+/dmog"
    "z4Xyrav1Q7lcLC+L80VxfllGGW6LizL5qEhqHIRDRzJFtfGw8Q5SFa//F7MLknu+OL/EstBrVfUy7n63Kkfy1F61utjAjcZui7tl"
    "qZyF8VQseqluYdKzj8HZcbedDLTb+pU8r5frWi3WSp5LVTerpbpcbjZrvZZ6c/lS1vVSL+VKvlbL5pVq8N9K68XFUp2v5SUpX5sA"
    "1dWu6qAjRKboLijuMer1z4Pxuq625DqKgm8p2D+8//GHt99g/NtijH5yzCFEqxyikpa8dTbAEGMKQdyAYEfMhaGN5UdsiNwst4P0"
    "tRhPHUR0opO3tEqHHRZJGIayBcH7UStyf5iLMfo3GpmohZZqJ3oXgtm0SJNWmq5sJXJrh6mDRTZrsdNtPSU+MoTSUpiu07XBGZHt"
    "zgrreMZcKDpM23KczkXtTQNI8GIz1FsdKUd+DIQEaiftFjk6AUvamrLK11U6KG+W94UuL5LoCjlu45+/EsFsrYwD5l6LoCNQjGFH"
    "P8AYyOBb6+5bXdMmfADeAKoCDe5N3PHJxn0i5VraDzltmj0iig04H+GCHjhvtoZAMS1LMJQQZ7C0nT3alsKYjvvNg/bK4My1hns7"
    "5EaIRk3nLvP5ajfAAYHhcYQltS9DlHQAmtS07n5CwMd2hjPjvUagAHe8zI5uXYiTVdMxHymHKbqVfdDsUI99sHEr9+lY8Cf2Qtix"
    "fEWgSPl6RkGbAr4COFkqIL8/jzPq1dK0+2IDtVq3LWunQkkyQ5kGhqAnzCiRMU8B5ayrYd+c1y+b9aJ5+WqxXki1upCXK7nAo9Vi"
    "8Xql6ovN4uJyWb/WrxD1y9Xr9WJRL9TLl4CC+uVK12qzmv06n3XSmoawtNWyqUx9VBSxUQaVx89L1NDD0PNhTMLxA2zfnbOlXWvU"
    "PmmQrNEOVhZUVwvMAPi4Fn4ZPBKasOfTzIxlmaMCy548oCoTItUTi2p+NbuTranHIYLzIlVGDOU/4H4NQyGGC8zdWpKFUaIBxTRF"
    "U2wjPgso1A79YTWsnDO/MkQxGqkSSFZQodq4AXFfV4zsL4zthxiuRG1UnIs/zaecmWdQqLAakQti0DnrorNGPcWfDJVzwVj5lSj+"
    "wuKuM0qQDtuUMQXUql3TIKoAoBKhzCBfIqtR3Hemnx8nBGAAyJ1Qk3NisEgy195B+58HmJRyEOf6iaxIJn8AgamaVm75tMoDcSsa"
    "AQrZWEFydMq1s59goDHZKyolEEV+nJ7dotzBnPS7QL3o2IOyq0aycDxWJFMXLaKaTXpcntwQybysDU8Da+g66amGjS5qDCAJvx8H"
    "TQVb82Poj0ioA/kuR1JG7jQKZKSscB61sJ9WNalg05/ehFsk251ujzVrzANPJCyoDjEGNeAtGIvKbvtoYKN38s4Aw9qKRNJiIASp"
    "yvXneGvKqhycVZ1RijfvwCSh1iTA6geQqlQ14Rb45ebzdPkGdPk9gqTOHJYtPQbelxDkmxNB/u8SZFA6qj2fqy8n7vyH487vYEED"
    "dPhlpIKoCFQaEK5gU8gkWoEg2ot68HLTIm2k4n0FIQ9RH8shS5SPzYIaBoZGj5BrliwScx71yBhwU620yfTR6wa8RchuY7aDGwKz"
    "JlCtkSCmFQrkDMSVdo7mLvPuQDz5UEfEiFMjVZd2/4igUz696SlBEyvfWyVavWV+mhSCR20wDGET329QCyL3AcS0sz5uwxlf/5Yi"
    "TmAAS9AfMumLQg2DZwacSmkCIaNpkUOQgTUO3hN2ZCykNoHOwBhQJnVdxipL9oROvTTU5iCt9yOAwOSMlhyyYwORQZEQALBPiLa3"
    "mETMGjUTVZOlNpJor7G5+2FoTY5LMeD8SOFtJItAR/KyoMKso0kUQm78AFtSBc8eRhj5mDwtW/QeIAsF8I/4wOhZnB3i6z0aMkQJ"
    "8X4szo1ZKhD3OxTXSRhiFEUq4elTn3DVYvee2PcT9n1zYt/Pw77fUkz+NeXpC84gLjFXgEzQ7R6oN/Jw+rvy8r4KO7lcX+YZrUGE"
    "H3N1DnLYKo8ft+NVzpE8/avrqWVnFC7BDWwm3zSTmARCAkk/8ViChM9T9+fk4mRrQBhNBoUFudg5+nHi6P/LHH31eY6+uhIfEsdG"
    "/DKMm64bwFQ5mGDk1CB+EV1fnej6ia6f6Poz0fX3ieakNKs1CC4kHnF2xjcO5ATemfVRINGsmgqmnugt2SXFv6zDNeR5oqupvni9"
    "NcT7i8b4EEVAVaHrI/BVWaN6Rc3cjq7dQcm2Ot/vRg8mh6E3S4gh6p/uVwXdVPmEC9iiuNV7cbMu0k0z1yhW5YHvgL+fUnQCnWTJ"
    "kkttOeHAyBrl2GAggdQt6LSN11COeCzos7PbOfUyEEO9hLMNiEmkduWwfemdQyUeDznN4lZkNHNJNgNEj+fmXmU0JZuQTdA6WcMC"
    "VK7K0fYlUnaKQoAHId3hHJ0JHcWNkA0cfQ9kHYl7RqJ0gVeOJTMcvDFybNIHFKOHb/m6Pt+Es7GJaInO0aV8AfZsGm7zUqsWjhBx"
    "urDPgI103WoPek0RMrTUqhAkl9YVU8/BpF6M1WpE5vy2Il0MBiv7sHNxOm/55vt3WdkTRX9K0Vcniv4sFD33g1Vm1nw5/uKYmSd+"
    "Mv46IEem4NO7oTRD/EP8DYT3N1fiE5plupNhLCXhI4SDmam1FY+L04gJCL7r48xBSmSxnELUc/PvKZniveMHj0jR+1HpD3R1cxZd"
    "xbrziwLw4P+A7p84/R+O068/z+nXV+ImvTA6fjPz9rt3zBRcuvj6Ika/PjH6E6M/MfpnYvTfSw+il+J8FEjcGaWZsitlEyP4nG5V"
    "AzNXpnREUs2WrlyB5wNm8ZcmZGqOeyp2Ew02lrIcwUZsupa6c7b08h5R3wF1SgarokGqEH0S9DMcX6SnbObLe5ov+Bp26PP9OGXK"
    "WwaR3Jiko6ZPSXq6+J4+ITH5SzlMQopQtZo+OBmLJJ81g4TimdGJNxflDQVnrrbpW550na7aIeA55pnpXUb95PuRj6ADgjg+imwY"
    "O5ypfZrYdHlopPKHJgC0iRZP3DkRf7bx+D1OIia5C0gwLehdOJzGZ7eOX3IQNCW3ccchCHE8BJAFfxjyzf3YuB0u6Q+BNPF2Fovq"
    "KMKt6XtuxnLsKOQpqLrVkbuMr28OYKcwTmbFYfKbDfLpiENKjBiIVjBn5+MPZ4BRhrqpdMf++O3HoRuDXeBqwrTpwp4vPFnGifE/"
    "ZfzrE+N/Dsb/zYiNT9hN/krmmOUwSF0LKicMSulF0whN+UJiAh3Gmt8iA+fv4YXeY7w59Of/hvIDFyx4CtMwvoggpCoeYQOlaL4A"
    "mOAGHfTp7v7/mef/+k/rjKD0"
)
_STALE_REVIEWED_CONTEXTS = json.loads(zlib.decompress(base64.b64decode(_STALE_REVIEWED_CONTEXTS_ZLIB_B64)))
_REVIEWED_CONTEXTS = json.loads(zlib.decompress(base64.b64decode(_REVIEWED_CONTEXTS_ZLIB_B64)))
_REVIEWED_IDS = {
    "A3": "DU-01-02/A3", "B3": "DU-01-02/B3",
    "B4": "DU-01-02/B4", "B5": "DU-01-02/B5",
}
_REVIEWED_ROLE_RECORDS = [
    {"role_id": "implementation", "goal_gate": False},
    {"role_id": "test-runner", "goal_gate": False},
    {"role_id": "code-review", "goal_gate": False},
    {"role_id": "semantic-alignment", "goal_gate": True},
    {"role_id": "evidence-rollup", "goal_gate": False},
]


class LocalSizingTests(unittest.TestCase):
    CANONICAL_PURPOSES = {
        "implementation": "implementation",
        "test-runner": "validation",
        "local-validation": "validation",
        "deployed-validation": "validation",
        "test-planning": "decomposition",
        "validation": "decomposition",
        "architecture": "decomposition",
        "auth": "decomposition",
        "security": "decomposition",
        "data-models": "decomposition",
        "data-contracts": "decomposition",
        "scaling": "decomposition",
        "runtime-operations": "decomposition",
        "product-semantics": "decomposition",
        "code-review": "review",
        "security-review": "review",
        "evidence-rollup": "review",
        "review-rollup": "review",
        "validation-rollup": "review",
        "rollup-editor": "review",
        "semantic-alignment": "goal-review",
        "semantic-review": "goal-review",
    }

    def default_template_roles(self, filename: str) -> list[dict]:
        payload = json.loads((ROOT / "team-templates" / filename).read_text(encoding="utf-8"))
        return [
            {"role_id": role["id"], "goal_gate": role.get("goal_gate", False)}
            for role in payload["roles"]
        ]

    def test_absent_opt_in_contract_preserves_legacy_route(self) -> None:
        result = sizing.qualify({"write_scope": ["src/a.py"]})
        self.assertEqual(result["status"], "legacy")
        self.assertEqual(result["assignments"], {})
        self.assertEqual(result["policy_version"], 1)

    def test_missing_or_null_contract_blocks_instead_of_falling_back_to_legacy(self) -> None:
        for context in ({"local_execution_v1": None}, {"local_execution_v1": {}}):
            with self.subTest(context=context):
                self.assertEqual(sizing.qualify(context)["status"], "blocked")

    def test_policy_rejects_unknown_fields_and_does_not_echo_values(self) -> None:
        context = make_context()
        context["local_execution_v1"]["provider"] = "private-provider-token-value"
        result = sizing.qualify(context)
        self.assertEqual(result["status"], "blocked")
        rendered = repr(result)
        self.assertIn("provider", rendered)
        self.assertNotIn("private-provider-token-value", rendered)

    def test_unknown_policy_and_purpose_block_without_echoing_policy_value(self) -> None:
        context = make_context()
        context["local_execution_v1"]["policy_id"] = "unknown-private-policy-value"
        result = sizing.qualify(context)
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["policy_id"])
        self.assertNotIn("unknown-private-policy-value", repr(result))

        context = make_context(purposes={"implementation": "autonomous"})
        self.assertEqual(sizing.qualify(context)["status"], "blocked")

    def test_contract_rejects_wrong_types_booleans_and_model_overrides(self) -> None:
        mutations = [
            ("changed_interfaces", True),
            ("unresolved_questions", [False]),
            ("complexity_flags", "migration"),
            ("role_purposes", ["implementation"]),
            ("model", "gpt-6-luna"),
            ("fallback_model", "gpt-6.1-sol"),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                context = make_context()
                context["local_execution_v1"][key] = value
                self.assertEqual(sizing.qualify(context)["status"], "blocked")

    def test_exact_unit_boundary_qualifies_and_one_step_over_requires_split(self) -> None:
        four_files = ["src/a.py", "src/b.py", "tests/a_test.py", "docs/decision.md"]
        three_criteria = [
            "Users can review the local acceptance result.",
            "The stored evidence remains available after restart.",
            "Invalid review data leaves the operation blocked.",
        ]
        exact = make_context(
            paths=four_files, criteria=three_criteria, interfaces=["local acceptance API"]
        )
        exact_result = sizing.qualify(exact)
        self.assertEqual(exact_result["status"], "qualified")
        self.assertEqual(exact_result["observed_counts"]["write_scope_files"], 4)
        self.assertEqual(exact_result["observed_counts"]["acceptance_criteria"], 3)
        self.assertEqual(exact_result["observed_counts"]["changed_interfaces"], 1)

        too_many_files = make_context(paths=[*four_files, "src/c.py"], criteria=three_criteria)
        self.assertEqual(sizing.qualify(too_many_files)["status"], "split_required")
        too_many_criteria = make_context(
            paths=four_files,
            criteria=[*three_criteria, "The operation keeps all evidence local."],
        )
        self.assertEqual(sizing.qualify(too_many_criteria)["status"], "split_required")
        too_many_interfaces = make_context(interfaces=["public interface one", "public interface two"])
        self.assertEqual(sizing.qualify(too_many_interfaces)["status"], "split_required")

    def test_coding_scope_requires_explicit_small_file_set_and_substantive_criteria(self) -> None:
        bad_paths = [
            "src", "src/", "../outside.py", "src/../outside.py", "/tmp/a.py", "C:/repo/a.py",
            "src/*.py", "src/a\\b.py", "README",
        ]
        for path in bad_paths:
            with self.subTest(path=path):
                result = sizing.qualify(make_context(paths=[path]))
                self.assertEqual(result["status"], "blocked")
        for path in ("Makefile", "LICENSE", "Dockerfile"):
            with self.subTest(conventional_file=path):
                self.assertEqual(sizing.qualify(make_context(paths=[path]))["status"], "qualified")
        self.assertEqual(sizing.qualify(make_context(paths=[]))["status"], "blocked")
        self.assertEqual(sizing.qualify(make_context(criteria=["done"]))["status"], "blocked")
        self.assertEqual(
            sizing.qualify(make_context(paths=["src/a.py", "src/a.py"]))["status"], "blocked"
        )

    def test_exact_extensionless_orchestrator_path_is_accepted_without_broadening_paths(self) -> None:
        orchestrator = "templates/local-automation-runtime/atlas-agent-orchestrator"
        self.assertEqual(sizing.qualify(make_context(paths=[orchestrator]))["status"], "qualified")

        accepted_suffixes = (orchestrator + ".py", orchestrator + ".sh")
        for path in accepted_suffixes:
            with self.subTest(suffixed_path=path):
                self.assertEqual(sizing.qualify(make_context(paths=[path]))["status"], "qualified")

        refused = (
            "templates/local-automation-runtime/Atlas-agent-orchestrator",
            orchestrator + "-extra",
            "atlas-agent-orchestrator",
            "other/atlas-agent-orchestrator",
            "templates/local-automation-runtime/atlas-agent-orchestrator-sibling",
            "/" + orchestrator,
            "~/" + orchestrator,
            "templates/local-automation-runtime/../atlas-agent-orchestrator",
            "templates/local-automation-runtime/./atlas-agent-orchestrator",
            "templates//local-automation-runtime/atlas-agent-orchestrator",
            "templates/local-automation-runtime/atlas-agent-orchestrator/",
            "templates/local-automation-runtime/atlas-agent-orchestrator*",
            "templates/local-automation-runtime/atlas-agent-orchestrator:stream",
            "templates\\local-automation-runtime\\atlas-agent-orchestrator",
        )
        for path in refused:
            with self.subTest(refused_path=path):
                self.assertEqual(sizing.qualify(make_context(paths=[path]))["status"], "blocked")

    def test_extensionless_orchestrator_retains_normal_sizing_and_contract_guards(self) -> None:
        path = "templates/local-automation-runtime/atlas-agent-orchestrator"
        four = [path, "src/a.py", "src/b.py", "docs/decision.md"]
        criteria = ["First behavior is observable.", "Second behavior is observable.", "Third behavior is observable."]
        exact = sizing.qualify(make_context(paths=four, criteria=criteria, interfaces=["local routing API"]))
        self.assertEqual(exact["status"], "qualified")
        self.assertEqual(exact["observed_counts"]["write_scope_files"], 4)
        self.assertEqual(exact["observed_counts"]["acceptance_criteria"], 3)
        self.assertEqual(exact["observed_counts"]["changed_interfaces"], 1)

        for context in (
            make_context(paths=[path, "src/a.py", "src/b.py", "docs/decision.md", "src/c.py"]),
            make_context(
                paths=[path],
                criteria=[
                    "First observable behavior is preserved.",
                    "Second observable behavior is preserved.",
                    "Third observable behavior is preserved.",
                    "Fourth observable behavior is preserved.",
                ],
            ),
            make_context(paths=[path], interfaces=["one", "two"]),
            make_context(paths=[path], questions=["Which route is authoritative?"]),
            make_context(paths=[path], flags=["security_or_authority"]),
        ):
            with self.subTest(context=context):
                self.assertNotEqual(sizing.qualify(context)["status"], "qualified")

        malformed = make_context(paths=[path])
        malformed["local_execution_v1"]["model"] = "gpt-6.1-sol"
        self.assertEqual(sizing.qualify(malformed)["status"], "blocked")
        route = sizing.qualify(
            make_context(paths=[path], purposes={"implementation": "implementation"}),
            roles=[{"role_id": "implementation"}],
        )
        self.assertEqual(route["assignments"]["implementation"]["model"], "gpt-6-luna")
        self.assertEqual(route["assignments"]["implementation"]["reasoning"], "medium")
        with self.assertRaisesRegex(ValueError, "no qualified local assignment"):
            sizing.assignment_for_task(
                {"role_id": "implementation", "work_item_context": make_context(paths=[path] * 5)}
            )

    def test_actual_du_01_02_three_path_packet_is_classified_after_path_correction(self) -> None:
        context = make_context(
            paths=[
                "templates/local-automation-runtime/atlas-agent-orchestrator",
                "templates/local-automation-runtime/tests/test_atlas_local_supervisor.py",
                "docs/local-supervisor.md",
            ],
            purposes={
                "implementation": "implementation",
                "code-review": "review",
                "goal-review": "goal-review",
            },
            interfaces=["Existing local orchestrator finite-cycle contract"],
        )
        roles = [
            {"role_id": "implementation"},
            {"role_id": "code-review"},
            {"role_id": "goal-review"},
        ]
        result = sizing.qualify(context, roles=roles)
        self.assertEqual(result["status"], "qualified", result["reasons"])
        self.assertEqual(result["observed_counts"]["write_scope_files"], 3)
        self.assertEqual(result["assignments"]["implementation"]["model"], "gpt-6-luna")
        self.assertEqual(result["assignments"]["implementation"]["reasoning"], "medium")
        self.assertEqual(result["assignments"]["code-review"]["model"], "gpt-6.1-sol")
        self.assertEqual(result["assignments"]["goal-review"]["reasoning"], "high")

    def test_questions_and_complexity_flags_require_decomposition_before_coding(self) -> None:
        purposes = {"implementation": "implementation", "scope-decomposer": "decomposition"}
        roles = [{"role_id": "implementation"}, {"role_id": "scope-decomposer"}]
        question = sizing.qualify(
            make_context(purposes=purposes, questions=["Which local state format is authoritative?"]),
            roles=roles,
        )
        self.assertEqual(question["status"], "decomposition_required")
        self.assertEqual(list(question["assignments"]), ["scope-decomposer"])
        self.assertNotIn("implementation", question["assignments"])
        security = sizing.qualify(
            make_context(purposes=purposes, flags=["security_or_authority"]), roles=roles
        )
        self.assertEqual(security["status"], "decomposition_required")
        self.assertIn("security_or_authority", sizing.COMPLEXITY_FLAGS)
        unknown_flag = sizing.qualify(make_context(flags=["large" ]))
        self.assertEqual(unknown_flag["status"], "blocked")

    def test_decomposition_only_can_route_open_complexity_without_promoting_coding(self) -> None:
        context = make_context(
            purposes={"scope-decomposer": "decomposition"},
            questions=["Which local state format is authoritative?"],
            flags=["migration"],
        )
        result = sizing.qualify(context, roles=[{"role_id": "scope-decomposer"}])
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["assignments"]["scope-decomposer"]["model"], "gpt-6.1-sol")
        self.assertEqual(result["assignments"]["scope-decomposer"]["reasoning"], "high")
        self.assertTrue(any("decomposition-only" in reason for reason in result["reasons"]))

    def test_decomposition_only_can_inspect_oversized_scope_without_coding_route(self) -> None:
        context = make_context(
            paths=["src/a.py", "src/b.py", "src/c.py", "src/d.py", "src/e.py"],
            criteria=[
                "The first acceptance behavior is observable.",
                "The second acceptance behavior is observable.",
                "The third acceptance behavior is observable.",
                "The fourth acceptance behavior is observable.",
            ],
            purposes={"scope-decomposer": "decomposition"},
            interfaces=["interface one", "interface two"],
        )
        result = sizing.qualify(context)
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["assignments"]["scope-decomposer"]["purpose"], "decomposition")

    def test_roles_must_have_explicit_fixed_purposes_and_gates_route_independently(self) -> None:
        purposes = {
            "implementation": "implementation",
            "test-runner": "validation",
            "code-review": "review",
            "semantic-alignment": "goal-review",
        }
        roles = [
            {"role_id": "implementation"},
            {"role_id": "test-runner"},
            {"role_id": "code-review"},
            {"role_id": "semantic-alignment", "goal_gate": True},
        ]
        result = sizing.qualify(make_context(purposes=purposes), roles=roles)
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["assignments"]["implementation"]["model"], "gpt-6-luna")
        self.assertEqual(result["assignments"]["test-runner"]["reasoning"], "medium")
        self.assertEqual(result["assignments"]["code-review"]["model"], "gpt-6.1-sol")
        self.assertEqual(result["assignments"]["semantic-alignment"]["purpose"], "goal-review")
        self.assertEqual(result["assignments"]["semantic-alignment"]["reasoning"], "high")

        relabeled = make_context(purposes={"implementation": "review"})
        self.assertEqual(sizing.qualify(relabeled)["status"], "blocked")
        missing = sizing.qualify(make_context(), roles=[{"role_id": "test-runner"}])
        self.assertEqual(missing["status"], "blocked")
        malformed_gate = sizing.qualify(
            make_context(purposes={"custom-review": "review"}),
            roles=[{"role_id": "custom-review", "goal_gate": "true"}],
        )
        self.assertEqual(malformed_gate["status"], "blocked")

    def test_canonical_roles_in_all_default_templates_keep_fixed_purposes(self) -> None:
        templates = (
            "planning-design-doc.json",
            "review-evidence-gate.json",
            "validation-evidence-gate.json",
            "work-item-change-lifecycle.json",
        )
        for filename in templates:
            with self.subTest(template=filename):
                roles = self.default_template_roles(filename)
                purposes = {
                    role["role_id"]: self.CANONICAL_PURPOSES[role["role_id"]]
                    for role in roles
                }
                contract_context = make_context(purposes=purposes)
                result = sizing.qualify(contract_context, roles=roles)
                self.assertEqual(result["status"], "qualified", result["reasons"])
                for role in roles:
                    self.assertEqual(
                        result["assignments"][role["role_id"]]["purpose"],
                        purposes[role["role_id"]],
                    )

    def test_actual_default_review_template_cannot_downgrade_security_review(self) -> None:
        roles = self.default_template_roles("review-evidence-gate.json")
        purposes = {
            role["role_id"]: self.CANONICAL_PURPOSES[role["role_id"]]
            for role in roles
        }
        purposes["security-review"] = "implementation"
        blocked = sizing.qualify(make_context(purposes=purposes), roles=roles)
        self.assertEqual(blocked["status"], "blocked")
        self.assertTrue(any("security-review purpose must be review" in reason for reason in blocked["reasons"]))

        purposes["security-review"] = "review"
        accepted = sizing.qualify(make_context(purposes=purposes), roles=roles)
        self.assertEqual(accepted["status"], "qualified")
        self.assertEqual(accepted["assignments"]["security-review"]["model"], "gpt-6.1-sol")

    def test_assignments_are_stable_and_assignment_for_task_fails_closed(self) -> None:
        context = make_context(
            purposes={"implementation": "implementation", "semantic-alignment": "goal-review"}
        )
        roles = [{"role_id": "implementation"}, {"role_id": "semantic-alignment", "goal_gate": True}]
        first = sizing.qualify(context, roles=roles)
        second = sizing.qualify(context, roles=roles)
        self.assertEqual(first, second)
        route = sizing.assignment_for_task(
            {"role_id": "implementation", "work_item_context": context}
        )
        self.assertEqual(route, first["assignments"]["implementation"])
        with self.assertRaisesRegex(ValueError, "no qualified local assignment"):
            sizing.assignment_for_task(
                {"role_id": "implementation", "work_item_context": make_context(flags=["migration"])}
            )

    def test_assignment_for_task_checks_entire_declared_packet_before_role_route(self) -> None:
        context = make_context(
            paths=["src/a.py", "src/b.py", "src/c.py", "src/d.py", "src/e.py"],
            purposes={"implementation": "implementation", "code-review": "review"},
        )
        with self.assertRaisesRegex(ValueError, "no qualified local assignment"):
            sizing.assignment_for_task({"role_id": "code-review", "work_item_context": context})

    def test_exact_reviewed_supervisor_contexts_route_all_roles_and_every_subset(self) -> None:
        for unit, context in _REVIEWED_CONTEXTS.items():
            with self.subTest(unit=unit):
                self.assertEqual(context["package_id"], _REVIEWED_IDS[unit])
                full = sizing.qualify(context)
                self.assertEqual(full["status"], "qualified", full["reasons"])
                self.assertEqual(full["policy_id"], "local-luna-unit-v1")
                self.assertEqual(full["policy_version"], 1)
                self.assertEqual(full["observed_counts"], {
                    "roles": 5, "coding_or_validation_roles": 2,
                    "write_scope_files": len(context["write_scope"]),
                    "acceptance_criteria": len(context["acceptance_criteria"]),
                    "changed_interfaces": 1, "unresolved_questions": 0,
                    "complexity_flags": len(context["local_execution_v1"]["complexity_flags"]),
                })
                admission = full["reviewed_supervisor_admission"]
                self.assertEqual(admission["routing_revision"], "supervisor-stronger-source-v1")
                self.assertEqual(admission["routing_amendment_sha256"],
                                 "e89402513a3eb784df37a2cef48fcc7ae62bb00ca919560134e15b3c1cad288b")
                self.assertEqual(
                    admission["review_evidence"],
                    [
                        {"artifact": "supervisor-cycle-binding-v2/scoped-amendment-review.json",
                         "sha256": "24f69c656f5947c647adf54623a5d5954db0d23c540a0dfea0273609bde76637"},
                        {"artifact": "supervisor-cycle-binding-v2/goal-amendment-review.json",
                         "sha256": "254da6221e325d64c52c2f3db247aaf1badd49e934fb81d129f2c25de630b5cf"},
                        {"artifact": "supervisor-cycle-binding-v2/integration-packets.json",
                         "sha256": "889d9a366fc67927c212079d63cb6bcbbc701d3475d3aad5145a648939d053b3"},
                        {"artifact": "team-templates/work-item-change-lifecycle.json",
                         "sha256": "bc09a362694d095028aa81498ba7a989051944a1a6505144783cfa019253912a"},
                    ],
                )
                self.assertEqual(admission["full_packet_counts"], full["observed_counts"])
                for purpose in ("implementation", "validation"):
                    role_id = "implementation" if purpose == "implementation" else "test-runner"
                    self.assertEqual(full["assignments"][role_id]["model"], "gpt-6.1-sol")
                    self.assertEqual(full["assignments"][role_id]["reasoning"], "high")
                self.assertEqual(full["assignments"]["semantic-alignment"]["purpose"], "goal-review")
                self.assertEqual(full["assignments"]["semantic-alignment"]["reasoning"], "high")
                for mask in range(1, 1 << 5):
                    subset = [role for i, role in enumerate(_REVIEWED_ROLE_RECORDS) if mask & (1 << i)]
                    result = sizing.qualify(context, roles=subset)
                    self.assertEqual(result["status"], "qualified", (unit, mask, result["reasons"]))
                    self.assertEqual(set(result["assignments"]), {r["role_id"] for r in subset})
                    self.assertEqual(result["observed_counts"]["roles"], len(subset))
                    self.assertEqual(
                        result["observed_counts"]["coding_or_validation_roles"],
                        sum(r["role_id"] in {"implementation", "test-runner"} for r in subset),
                    )
                    self.assertEqual(result["reviewed_supervisor_admission"]["full_packet_counts"]["roles"], 5)
                for role in _REVIEWED_ROLE_RECORDS:
                    task = {**role, "work_item_context": context}
                    assignment = sizing.assignment_for_task(task)
                    self.assertEqual(assignment, full["assignments"][role["role_id"]])

    def test_old_reviewed_contexts_are_refused_after_binding_refresh(self) -> None:
        for unit, context in _STALE_REVIEWED_CONTEXTS.items():
            with self.subTest(unit=unit):
                result = sizing.qualify(context)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["assignments"], {})

    def test_reviewed_packet_known_ids_never_fall_back_when_contract_is_missing(self) -> None:
        for unit, context in _REVIEWED_CONTEXTS.items():
            for mutation in ("missing", None, [], "malformed"):
                changed = copy.deepcopy(context)
                if mutation == "missing":
                    changed.pop("local_execution_v1")
                else:
                    changed["local_execution_v1"] = mutation
                result = sizing.qualify(changed)
                self.assertEqual(result["status"], "blocked", (unit, mutation))
                self.assertEqual(result["assignments"], {})

    def test_reviewed_packet_context_mutations_and_question_guard_fail_closed(self) -> None:
        def mutate(context: dict, field: str) -> None:
            if field == "package_hash":
                context[field] = "0" * 64
            elif field == "package_id":
                context[field] = "DU-01-02/OTHER"
            elif field == "goal":
                context[field] = "changed goal"
            elif field == "write_scope":
                context[field] = ["src/changed.py"]
            elif field == "acceptance_criteria":
                context[field] = ["Changed acceptance criterion remains substantive."]
            elif field == "contract_policy":
                context["local_execution_v1"]["policy_id"] = "other-policy"
            elif field == "role_purpose":
                context["local_execution_v1"]["role_purposes"]["implementation"] = "review"
            elif field == "interfaces":
                context["local_execution_v1"]["changed_interfaces"] = ["changed interface"]
            elif field == "flags":
                context["local_execution_v1"]["complexity_flags"] = []
            elif field == "workflow_request":
                context["workflow_request"]["required_outputs"].append("new output")
            elif field == "source_metadata":
                context["spec_hash"] = "0" * 64
            else:
                context["arbitrary_extra"] = "arbitrary"

        fields = (
            "package_hash", "package_id", "goal", "write_scope", "acceptance_criteria",
            "contract_policy", "role_purpose", "interfaces", "flags", "workflow_request",
            "source_metadata", "extra",
        )
        for unit, context in _REVIEWED_CONTEXTS.items():
            for field in fields:
                changed = copy.deepcopy(context)
                mutate(changed, field)
                result = sizing.qualify(changed)
                expected = "decomposition_required" if field == "package_id" else "blocked"
                self.assertEqual(result["status"], expected, (unit, field))
                self.assertEqual(result["assignments"], {})
            changed = copy.deepcopy(context)
            changed["local_execution_v1"]["unresolved_questions"] = ["Unresolved decision."]
            result = sizing.qualify(changed)
            self.assertNotEqual(result["status"], "qualified")
            self.assertEqual(result["assignments"], {})

    def test_reviewed_match_cannot_waive_questions_even_if_match_helper_says_true(self) -> None:
        context = copy.deepcopy(_REVIEWED_CONTEXTS["A3"])
        context["local_execution_v1"]["unresolved_questions"] = ["Unresolved decision."]
        packet = sizing.REVIEWED_SUPERVISOR_PACKETS_V1[context["package_id"]]
        with mock.patch.object(sizing, "_reviewed_supervisor_packet", return_value=(packet, True)):
            result = sizing.qualify(context)
        self.assertEqual(result["status"], "decomposition_required")
        self.assertNotIn("implementation", result["assignments"])
        self.assertNotIn("test-runner", result["assignments"])

    def test_reviewed_subset_cannot_hide_full_packet_scope_limits_or_unknown_roles(self) -> None:
        context = copy.deepcopy(_REVIEWED_CONTEXTS["A3"])
        review_only = [{"role_id": "code-review", "goal_gate": False}]
        too_many = copy.deepcopy(context)
        too_many["write_scope"].append("src/extra.py")
        self.assertEqual(sizing.qualify(too_many, roles=review_only)["status"], "blocked")
        for roles in (
            [{"role_id": "semantic-alignment", "goal_gate": "true"}],
            [{"role_id": "semantic-alignment", "goal_gate": True, "id": "other"}],
            [{"role_id": " semantic-alignment ", "goal_gate": True}],
            [{"role_id": "unknown", "goal_gate": False}],
            [],
        ):
            result = sizing.qualify(context, roles=roles)
            self.assertEqual(result["status"], "blocked", roles)

    def test_full_packet_size_limits_remain_active_even_if_match_helper_says_true(self) -> None:
        for field, value in (
            ("write_scope", ["a.py", "b.py", "c.py", "d.py", "e.py"]),
            ("acceptance_criteria", [
                "Criterion one remains substantive.", "Criterion two remains substantive.",
                "Criterion three remains substantive.", "Criterion four remains substantive.",
            ]),
        ):
            context = copy.deepcopy(_REVIEWED_CONTEXTS["A3"])
            context[field] = value
            packet = sizing.REVIEWED_SUPERVISOR_PACKETS_V1[context["package_id"]]
            with mock.patch.object(sizing, "_reviewed_supervisor_packet", return_value=(packet, True)):
                result = sizing.qualify(context, roles=[{"role_id": "code-review", "goal_gate": False}])
            self.assertEqual(result["status"], "split_required", field)
            self.assertEqual(result["assignments"], {})

    def test_unregistered_flags_keep_default_route_and_decomposition_refusal(self) -> None:
        context = make_context(flags=["cross_component_protocol"])
        result = sizing.qualify(context)
        self.assertEqual(result["status"], "decomposition_required")
        self.assertEqual(result["assignments"], {})
        self.assertEqual(result["policy_version"], 1)
        safe = sizing.qualify(make_context())
        self.assertEqual(safe["assignments"]["implementation"]["model"], "gpt-6-luna")
        self.assertEqual(safe["assignments"]["implementation"]["reasoning"], "medium")

    def test_ordinary_role_aliases_preserve_key_presence_precedence(self) -> None:
        context = make_context()
        baseline = sizing.qualify(context, roles=[{"role_id": "implementation"}])
        self.assertEqual(baseline["status"], "qualified")

        conflicting = sizing.qualify(
            context, roles=[{"role_id": "implementation", "id": "other"}]
        )
        self.assertEqual(conflicting["status"], "qualified")
        self.assertIn("implementation", conflicting["assignments"])
        self.assertNotIn("other", conflicting["assignments"])

        null_primary = sizing.qualify(
            context, roles=[{"role_id": None, "id": "implementation"}]
        )
        self.assertEqual(null_primary["status"], "blocked")

        null_alternate = sizing.qualify(
            context, roles=[{"role_id": "implementation", "id": None}]
        )
        self.assertEqual(null_alternate["status"], "qualified")
        id_only = sizing.qualify(context, roles=[{"id": "implementation"}])
        self.assertEqual(id_only["status"], "qualified")
        self.assertIn("implementation", id_only["assignments"])

    def test_reviewed_role_aliases_are_strict_and_id_only_task_route_is_consistent(self) -> None:
        context = _REVIEWED_CONTEXTS["A3"]
        for role in (
            {"role_id": "implementation", "id": None, "goal_gate": False},
            {"role_id": None, "id": "implementation", "goal_gate": False},
            {"role_id": "implementation", "id": "other", "goal_gate": False},
        ):
            with self.subTest(role=role):
                self.assertEqual(sizing.qualify(context, roles=[role])["status"], "blocked")

        alias_role = {"id": "implementation", "goal_gate": False}
        result = sizing.qualify(context, roles=[alias_role])
        self.assertEqual(result["status"], "qualified", result["reasons"])
        self.assertEqual(result["assignments"]["implementation"]["model"], "gpt-6.1-sol")
        task_assignment = sizing.assignment_for_task(
            {**alias_role, "work_item_context": context}
        )
        self.assertEqual(task_assignment, result["assignments"]["implementation"])


if __name__ == "__main__":
    unittest.main()
