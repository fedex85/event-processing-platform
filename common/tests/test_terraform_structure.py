"""Static consistency checks for the Terraform code.

Terraform itself is not available to the test suite, so these tests cannot prove the
configuration is valid (run ``terraform validate`` for that; CI does). They catch the typos
that are easy to make without it: a module input that does not exist, a required input that
is missing, a reference to an undeclared variable or output.
"""

import json
import re
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[2] / "infra"
MODULES = INFRA / "modules"

_STRING = re.compile(r'"(?:\\.|[^"\\])*"')


def _code(path: Path) -> str:
    """The file without comments and without the contents of strings."""
    lines = [line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")]
    return _STRING.sub('""', "\n".join(lines))


def _blocks(text: str, kind: str) -> dict[str, str]:
    """Top-level ``kind "name" { ... }`` blocks, which formatted code closes at column 0."""
    found: dict[str, str] = {}
    for match in re.finditer(rf'^{kind} "(\w+)" \{{\n(.*?)^\}}$', text, flags=re.M | re.S):
        found[match.group(1)] = match.group(2)
    return found


def _variables(path: Path) -> tuple[set[str], set[str]]:
    """(declared, required) variable names of a Terraform directory's ``variable`` blocks."""
    text = path.read_text()
    declared: set[str] = set()
    required: set[str] = set()
    for name, body in _blocks(text, "variable").items():
        declared.add(name)
        if not re.search(r"^  default\s*=", body, flags=re.M):
            required.add(name)
    return declared, required


def _module_dirs() -> list[Path]:
    return sorted(path for path in MODULES.iterdir() if path.is_dir())


def _module_calls() -> dict[str, tuple[str, set[str]]]:
    """name -> (module directory name, input names given) for the calls in the root main.tf."""
    calls: dict[str, tuple[str, set[str]]] = {}
    raw = (INFRA / "main.tf").read_text()
    for name, body in _blocks(raw, "module").items():
        source = re.search(r'source\s*=\s*"\./modules/(\w+)"', body)
        assert source, f"module {name} has no local source"
        inputs = set(re.findall(r"^  (\w+)\s*=", body, flags=re.M))
        calls[name] = (source.group(1), inputs - {"source", "depends_on", "count"})
    return calls


def test_the_expected_modules_exist() -> None:
    names = {path.name for path in _module_dirs()}

    assert names == {
        "apis",
        "artifact_registry",
        "bigquery",
        "cloud_run_service",
        "github_wif",
        "monitoring",
        "pubsub",
        "secrets",
        "service_accounts",
    }


@pytest.mark.parametrize(
    "path", sorted(INFRA.rglob("*.tf")), ids=lambda p: str(p.relative_to(INFRA))
)
def test_braces_and_brackets_are_balanced(path: Path) -> None:
    text = _code(path)

    for opening, closing in (("{", "}"), ("[", "]"), ("(", ")")):
        assert text.count(opening) == text.count(closing), f"unbalanced {opening}{closing}"


@pytest.mark.parametrize(
    "path", sorted(INFRA.rglob("*.tf")), ids=lambda p: str(p.relative_to(INFRA))
)
def test_literal_template_placeholders_are_escaped(path: Path) -> None:
    # Inside a Terraform string "${x}" is interpolation. Text that merely mentions a
    # placeholder (like the SQL template's) must write "$${x}".
    for match in re.finditer(r'"([^"\n]*\$\{(?:project_id|dataset)\}[^"\n]*)"', path.read_text()):
        text = match.group(1)
        assert "$${" in text or "var." in text or "local." in text, text


def test_every_module_call_passes_exactly_the_inputs_the_module_declares() -> None:
    for name, (directory, given) in _module_calls().items():
        declared, required = _variables(MODULES / directory / "main.tf")

        assert given <= declared, f"{name}: unknown inputs {sorted(given - declared)}"
        assert required <= given, f"{name}: missing inputs {sorted(required - given)}"


def test_root_references_only_declared_variables() -> None:
    declared, _ = _variables(INFRA / "variables.tf")
    used: set[str] = set()
    for path in (INFRA / "main.tf", INFRA / "outputs.tf"):
        used |= set(re.findall(r"\bvar\.(\w+)", path.read_text()))

    assert used <= declared, sorted(used - declared)


def test_every_root_variable_is_used() -> None:
    declared, _ = _variables(INFRA / "variables.tf")
    text = (INFRA / "main.tf").read_text() + (INFRA / "outputs.tf").read_text()

    unused = {name for name in declared if f"var.{name}" not in text}

    assert not unused, sorted(unused)


def test_root_only_reads_outputs_that_modules_declare() -> None:
    calls = _module_calls()
    text = (INFRA / "main.tf").read_text() + (INFRA / "outputs.tf").read_text()

    for module, output in re.findall(r"\bmodule\.(\w+)(?:\[\*\])?\.(\w+)", text):
        directory = calls[module][0]
        declared_outputs = set(
            re.findall(r'^output "(\w+)"', (MODULES / directory / "main.tf").read_text(), re.M)
        )
        assert output in declared_outputs, (
            f"module.{module}.{output} is not an output of {directory}"
        )


def test_modules_use_only_their_own_variables() -> None:
    for directory in _module_dirs():
        path = directory / "main.tf"
        declared, _ = _variables(path)
        used = set(re.findall(r"\bvar\.(\w+)", path.read_text()))

        assert used <= declared, f"{directory.name}: {sorted(used - declared)}"


@pytest.mark.parametrize("name", ["staging", "prod"])
def test_example_tfvars_only_set_declared_variables(name: str) -> None:
    declared, required = _variables(INFRA / "variables.tf")
    text = (INFRA / "environments" / f"{name}.tfvars.example").read_text()
    given = set(re.findall(r"^(\w+)\s*=", text, flags=re.M))

    assert given <= declared
    assert required <= given


def test_environment_value_matches_what_the_services_accept() -> None:
    text = (INFRA / "variables.tf").read_text()

    assert 'contains(["staging", "prod"], var.environment)' in text


def test_table_schemas_are_valid_json_with_the_partition_columns() -> None:
    events = {f["name"] for f in json.loads((INFRA / "schemas" / "stock_events.json").read_text())}
    alerts = {f["name"] for f in json.loads((INFRA / "schemas" / "stock_alerts.json").read_text())}
    bigquery = (MODULES / "bigquery" / "main.tf").read_text()

    assert {"occurred_at", "store_id", "sku"} <= events
    assert {"detected_at", "store_id", "sku"} <= alerts
    assert 'field = "occurred_at"' in bigquery
    assert 'field = "detected_at"' in bigquery


def test_the_processor_is_never_publicly_invokable() -> None:
    main = (INFRA / "main.tf").read_text()
    block = _blocks(main, "module")["processor_service"]

    assert "allow_unauthenticated = false" in block
    assert "pubsub_push" in block


def test_no_service_account_keys_or_secret_values_are_created() -> None:
    for path in INFRA.rglob("*.tf"):
        text = path.read_text()
        assert "google_service_account_key" not in text
        assert "google_secret_manager_secret_version" not in text
