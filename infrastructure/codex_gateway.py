from __future__ import annotations

import json
from pathlib import Path

from domain.errors import AppError
from domain.generation import extract_json_payload
from domain.models import Scene, Story, parse_story
from infrastructure.process_runner import SubprocessRunner


# Codex CLIに台本JSONの作成を依頼する実装。
class CodexCliStoryPlanner:
    def __init__(
        self,
        runner: SubprocessRunner,
        codex_bin: str = "codex",
        model: str | None = None,
        sandbox: str = "workspace-write",
    ):
        self._runner = runner
        self._codex_bin = codex_bin
        self._model = model
        self._sandbox = sandbox

    def plan_story(self, topic: str, slug: str, scene_count: int, root: Path, tmp_dir: Path) -> Story:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        schema_path = tmp_dir / "story.schema.json"
        output_path = tmp_dir / "story.codex.json"
        # Codexの出力をJSONスキーマで縛り、後段のparse_storyが扱える形にする。
        schema_path.write_text(json.dumps(_story_schema(scene_count), ensure_ascii=False, indent=2), encoding="utf-8")

        prompt = _story_prompt(topic, slug, scene_count)
        cmd = self._base_cmd(root)
        cmd.extend(["--output-schema", str(schema_path), "--output-last-message", str(output_path), prompt])
        self._runner.run(cmd)

        if not output_path.exists():
            raise AppError(f"Codex did not write story output: {output_path}")
        # 応答にコードフェンス等が混ざっても、JSONだけを取り出してからパースする。
        data = extract_json_payload(output_path.read_text(encoding="utf-8"))
        return parse_story(data)

    def _base_cmd(self, root: Path) -> list[str]:
        # repo外から呼ばれても、--cdで対象リポジトリを明示する。
        cmd = [
            self._runner.which(self._codex_bin),
            "exec",
            "--cd",
            str(root),
            "--skip-git-repo-check",
            "--sandbox",
            self._sandbox,
        ]
        if self._model:
            cmd.extend(["--model", self._model])
        return cmd


# Codex CLIの$imagegenを使って、シーンごとの画像を生成する実装。
class CodexCliImageGenerator:
    def __init__(
        self,
        runner: SubprocessRunner,
        codex_bin: str = "codex",
        model: str | None = None,
        sandbox: str = "workspace-write",
    ):
        self._runner = runner
        self._codex_bin = codex_bin
        self._model = model
        self._sandbox = sandbox

    def generate_image(self, topic: str, scene: Scene, index: int, total: int, output_path: Path, root: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prompt = _image_prompt(topic, scene, index, total, output_path)
        self._runner.run([*self._base_cmd(root), prompt])
        # Codex側が画像添付だけで終わった場合を検出し、期待パスに保存されていることを保証する。
        if not output_path.exists():
            raise AppError(f"Codex image generation did not create expected file: {output_path}")

    def _base_cmd(self, root: Path) -> list[str]:
        # 画像生成も設定されたサンドボックスで実行し、指定パスへのPNG保存を許可する。
        cmd = [
            self._runner.which(self._codex_bin),
            "exec",
            "--cd",
            str(root),
            "--skip-git-repo-check",
            "--sandbox",
            self._sandbox,
        ]
        if self._model:
            cmd.extend(["--model", self._model])
        return cmd


def _story_schema(scene_count: int) -> dict[str, object]:
    # シーン数をmin/maxで固定し、台本の過不足をCodex出力時点で抑制する。
    scene_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "image", "on_screen_text", "narration", "keywords"],
        "properties": {
            "id": {"type": "string"},
            "image": {"type": "string"},
            "on_screen_text": {"type": "string"},
            "narration": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "scenes"],
        "properties": {
            "title": {"type": "string"},
            "scenes": {
                "type": "array",
                "minItems": scene_count,
                "maxItems": scene_count,
                "items": scene_schema,
            },
        },
    }


def _story_prompt(topic: str, slug: str, scene_count: int) -> str:
    # 台本生成の品質条件とファイル命名規則をCodexへ明示する。
    return f"""
日本語のショート動画台本JSONを作ってください。

テーマ: {topic}
シーン数: {scene_count}
ID接頭辞: {slug}

条件:
- AWS/IT初心者にも伝わる、テンポのよい60秒前後の解説にする
- 各シーンのnarrationは自然な日本語で1-2文
- on_screen_textは短く、改行を含めてもよい
- imageは images/{slug}_01.png のように連番にする
- keywordsは字幕や画像プロンプトに使える重要語を2-4個
- 出力は指定されたJSONスキーマに厳密に従う
""".strip()


def _image_prompt(topic: str, scene: Scene, index: int, total: int, output_path: Path) -> str:
    # 字幕を後で載せるため、画像自体には文字を入れず下部余白を残す。
    keywords = ", ".join(scene.keywords) if scene.keywords else scene.on_screen_text.replace("\n", ", ")
    return f"""
$imagegen

Generate one high-quality vertical image for a Japanese educational short video.

Save the final PNG file to this exact path:
{output_path}

Image requirements:
- Canvas: 1024x1536 portrait
- Style: premium editorial technology illustration, polished, modern, high contrast, cinematic lighting
- Subject: {topic}
- Scene {index}/{total}: {scene.on_screen_text}
- Narration context: {scene.narration}
- Key visual ideas: {keywords}
- Use abstract cloud architecture, data flow, and infrastructure metaphors where useful
- Do not include official AWS logos, trademarks, watermarks, UI screenshots, or legible text
- Leave comfortable lower-third space so video subtitles remain readable

Do not finish until the PNG exists at the requested path.
""".strip()
