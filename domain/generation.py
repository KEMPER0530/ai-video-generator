from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import AppError
from .models import Scene, Story


# 動画の自動生成は長くなりすぎないよう、1回あたりのシーン数を制限する。
def normalize_scene_count(value: int) -> int:
    count = int(value)
    if count < 1 or count > 12:
        raise AppError("scene_count must be between 1 and 12")
    return count


# 日本語トピックでもファイル名に使えるよう、ASCII部分だけでslugを作る。
def slugify_topic(topic: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", topic.lower())
    if tokens:
        return "_".join(tokens[:4])
    return "generated"


# ユーザー指定slugは、ファイル名に使いやすい小文字ASCIIへそろえる。
def normalize_slug(slug: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")
    if not normalized:
        raise AppError("slug must contain at least one ASCII letter or number")
    return normalized


def scene_id(slug: str, index: int) -> str:
    # 画像名・音声名・台本内IDを同じ連番規則にする。
    return f"{slug}_{index:02d}"


def scene_image_ref(slug: str, index: int, images_dir: str = "images") -> str:
    return (Path(images_dir) / f"{scene_id(slug, index)}.png").as_posix()


def generated_story_path(root: Path, stories_dir: str, slug: str) -> Path:
    # 生成台本は既存サンプルと区別できる命名にする。
    base = Path(stories_dir)
    if not base.is_absolute():
        base = root / base
    return base / f"story.generated.{slug}.json"


def extract_json_payload(text: str) -> dict[str, Any]:
    # Codexの応答はコードフェンスや前置きが混ざる場合があるため、JSON部分だけを取り出す。
    payload = text.strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```(?:json)?\s*", "", payload)
        payload = re.sub(r"\s*```$", "", payload)
    if not payload.startswith(("{", "[")):
        start = payload.find("{")
        end = payload.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise AppError("Codex did not return a JSON object")
        payload = payload[start : end + 1]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AppError(f"Codex returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AppError("Codex JSON response must be an object")
    return data


def canonicalize_generated_story(story: Story, topic: str, slug: str, scene_count: int, images_dir: str = "images") -> Story:
    # Codexの自由な出力を、後続処理が期待するID/画像パス規則へ固定する。
    if len(story.scenes) != scene_count:
        raise AppError(f"Codex story must contain exactly {scene_count} scenes")

    scenes: list[Scene] = []
    for idx, scene in enumerate(story.scenes, start=1):
        on_screen_text = scene.on_screen_text.strip()
        narration = scene.narration.strip()
        if not on_screen_text:
            raise AppError(f"scene[{idx}] missing on_screen_text")
        if not narration:
            raise AppError(f"scene[{idx}] missing narration")
        scenes.append(
            Scene(
                id=scene_id(slug, idx),
                image=scene_image_ref(slug, idx, images_dir),
                on_screen_text=on_screen_text,
                narration=narration,
                keywords=scene.keywords,
            )
        )

    title = story.title.strip() or f"{topic} ショート解説"
    return Story(title=title, scenes=tuple(scenes))


def story_to_json_data(story: Story) -> dict[str, Any]:
    # dataclassを、story JSONとして保存できる素朴なdictへ戻す。
    scenes: list[dict[str, Any]] = []
    for scene in story.scenes:
        item: dict[str, Any] = {
            "id": scene.id,
            "image": scene.image,
            "on_screen_text": scene.on_screen_text,
            "narration": scene.narration,
        }
        if scene.keywords:
            item["keywords"] = list(scene.keywords)
        scenes.append(item)
    return {"title": story.title, "scenes": scenes}
