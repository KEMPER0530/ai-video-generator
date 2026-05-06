from __future__ import annotations

# 実際のCodex CLIを呼ばず、コマンド組み立てと出力検証だけを確認する。
import json
from pathlib import Path

import pytest

from domain.errors import AppError
from domain.models import Scene
from infrastructure.codex_gateway import CodexCliImageGenerator, CodexCliStoryPlanner


class FakeRunner:
    def __init__(self, *, write_story: bool = True, write_image: bool = True):
        self.write_story = write_story
        self.write_image = write_image
        self.calls: list[list[str]] = []

    def which(self, bin_name: str) -> str:
        return f"/usr/local/bin/{bin_name}"

    def run(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        self.calls.append(cmd)
        if "--output-last-message" in cmd:
            output_path = Path(cmd[cmd.index("--output-last-message") + 1])
            if self.write_story:
                output_path.write_text(json.dumps(_story_payload()), encoding="utf-8")
            return

        if self.write_image:
            prompt = cmd[-1]
            lines = prompt.splitlines()
            output_path = Path(lines[lines.index("Save the final PNG file to this exact path:") + 1])
            output_path.write_text("png", encoding="utf-8")


def _story_payload() -> dict[str, object]:
    return {
        "title": "Lambda intro",
        "scenes": [
            {
                "id": "s1",
                "image": "images/s1.png",
                "on_screen_text": "Lambda runs code",
                "narration": "Lambda runs code when events arrive.",
                "keywords": ["Lambda", "events"],
            },
            {
                "id": "s2",
                "image": "images/s2.png",
                "on_screen_text": "No server upkeep",
                "narration": "You focus on code instead of server maintenance.",
                "keywords": ["serverless"],
            },
        ],
    }


def test_codex_story_planner_writes_schema_and_parses_output(tmp_path: Path) -> None:
    runner = FakeRunner()
    planner = CodexCliStoryPlanner(runner, codex_bin="codex", model="gpt-5.4")

    story = planner.plan_story("AWS Lambda", "lambda", 2, tmp_path, tmp_path / "tmp")

    assert story.title == "Lambda intro"
    assert story.scenes[0].narration == "Lambda runs code when events arrive."
    command = runner.calls[0]
    assert command[:5] == ["/usr/local/bin/codex", "exec", "--cd", str(tmp_path), "--skip-git-repo-check"]
    assert command[command.index("--model") + 1] == "gpt-5.4"
    schema_path = Path(command[command.index("--output-schema") + 1])
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["scenes"]["minItems"] == 2
    assert "AWS Lambda" in command[-1]


def test_codex_story_planner_errors_when_output_is_missing(tmp_path: Path) -> None:
    planner = CodexCliStoryPlanner(FakeRunner(write_story=False))

    with pytest.raises(AppError, match="did not write story output"):
        planner.plan_story("AWS Lambda", "lambda", 2, tmp_path, tmp_path / "tmp")


def test_codex_image_generator_invokes_imagegen_and_checks_output(tmp_path: Path) -> None:
    runner = FakeRunner()
    generator = CodexCliImageGenerator(runner, model="gpt-5.4")
    scene = Scene("lambda_01", "images/lambda_01.png", "Events trigger code", "Lambda reacts to events.", ("events",))
    output_path = tmp_path / "images" / "lambda_01.png"

    generator.generate_image("AWS Lambda", scene, 1, 6, output_path, tmp_path)

    assert output_path.read_text(encoding="utf-8") == "png"
    command = runner.calls[0]
    assert command[command.index("--model") + 1] == "gpt-5.4"
    assert "$imagegen" in command[-1]
    assert "1024x1536 portrait" in command[-1]
    assert str(output_path) in command[-1]


def test_codex_image_generator_errors_when_expected_file_is_missing(tmp_path: Path) -> None:
    generator = CodexCliImageGenerator(FakeRunner(write_image=False))
    scene = Scene("lambda_01", "images/lambda_01.png", "Events trigger code", "Lambda reacts to events.", ())

    with pytest.raises(AppError, match="did not create expected file"):
        generator.generate_image("AWS Lambda", scene, 1, 1, tmp_path / "images" / "lambda_01.png", tmp_path)
