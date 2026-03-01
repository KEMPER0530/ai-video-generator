# ai-video-generator

取得済みの画像ファイルと台本JSONから、音声・字幕・動画ファイルを生成するプロダクトです。  
画像生成は行いません。

## 最短手順（これだけでOK）

1. 画像を `images/` に置く  
2. 台本を `stories/<your-story>.json` に書く  
3. 実行する（Docker）

```bash
docker build -f docker/Dockerfile -t ai-video-generator-pipeline:latest .
docker run --rm -v "$(pwd):/work" -w /work ai-video-generator-pipeline:latest \
  all --config configs/config.docker.cpu.json --story stories/<your-story>.json --images-dir ../images
```

出力先:
- `outputs/docker-all/output.mp4`
  - 最終生成される動画ファイル（投稿対象）
- `outputs/docker-all/subtitles.srt`
  - 字幕テキストと表示タイミングの標準形式ファイル（確認・他ツール連携用）
- `outputs/docker-all/subtitles.ass`
  - 装飾付き字幕ファイル（アニメーションやスタイル情報を含む）
- `outputs/docker-all/audio/narration.wav`
  - 全シーンを連結したナレーション音声（動画の音声トラック元）

## 入力ファイル

- `configs/config.docker.cpu.json`（解像度、fps、TTS設定）
- `stories/story*.json`（シーンごとの画像パス・字幕文・ナレーション文）
- 画像ファイル（各シーンで `image` に指定）

## story JSON 形式

```json
{
  "title": "AWS雑学 30秒",
  "scenes": [
    {
      "id": "aws1",
      "image": "images/aws1.png",
      "on_screen_text": "AWSは2006年に本格始動",
      "narration": "AWSの本格スタートは2006年。",
      "keywords": ["AWS", "2006年", "本格始動"]
    }
  ]
}
```

- `image` は通常必須
- 音声は `narration` を使用
- 動画に焼き込む字幕は「キーワード強調表示」
  - `keywords` があればそれを優先
  - `keywords` がなければ `on_screen_text` / `narration` から自動抽出
- 相対パスは `story.json` のあるディレクトリ基準で解決
  - 例: `stories/story.aws.json` で `image: "images/a.png"` の場合、`images/a.png`（リポジトリ直下）も自動探索
- TTS は `gTTS` を使用（実行時にインターネット接続が必要）
- 字幕ON/OFFは `subtitles.enabled` またはCLIで切り替え
- 画像サイズはデフォルトで「入力画像の元サイズをそのまま使用」
  - `project.use_source_size: true`（既定）
  - この場合、全シーン画像の解像度が同じである必要があります
- 動画尺の上限を指定可能
  - `project.max_duration_sec`（秒、`0` または未指定で無制限）
  - 例: `60` を指定すると 1分以内に自動調整

動画への字幕焼き込み仕様:
- `use_source_size=true` なら入力画像サイズのまま出力
- `use_source_size=false` なら `width` x `height` へ scale/crop
- 画面中央にキーワードを大きく表示
- ポップイン + フェードアウトのアニメーション付き
- 安全マージンを確保し、文字切れを抑制

字幕切り替え:
- デフォルト: `configs/config.docker.cpu.json` の `subtitles.enabled` に従う
- 強制OFF: `--no-subtitles`
- 強制ON: `--with-subtitles`

尺の上限切り替え:
- デフォルト: `project.max_duration_sec`
- 実行時上書き: `--max-duration-sec 60`

必須パラメータ:
- `--config`
- `--story`
- `--images-dir`

`--images-dir` の挙動:
- `image` が相対パスなら `--images-dir` 基準で解決
- `image` を省略したシーンは `<id>.png` を `--images-dir` から自動解決

## 実行コマンド（Docker）

### docker run で直接実行（これのみ）

```bash
docker build -f docker/Dockerfile -t ai-video-generator-pipeline:latest .
docker run --rm -v "$(pwd):/work" -w /work ai-video-generator-pipeline:latest \
  all --config configs/config.docker.cpu.json --story stories/<your-story>.json --images-dir ../images
```

生成物のクリーンアップ:

```bash
# 指定configの out_dir だけ削除
docker run --rm -v "$(pwd):/work" -w /work ai-video-generator-pipeline:latest \
  clean --config configs/config.docker.cpu.json

# outputs/ 以下を全部削除
docker run --rm -v "$(pwd):/work" -w /work ai-video-generator-pipeline:latest \
  clean --all
```

## コマンド一覧

- `doctor`: ffmpeg/ffprobe/TTS設定を検証
- `tts`: シーン別音声 + `narration.wav` を生成
- `srt`: シーン長ベースで `subtitles.srt` を生成
- `render`: 画像 + 音声 + 字幕で `output.mp4` を生成
- `all`: `tts -> srt -> render`
- `clean`: 生成済みの `outputs` を削除
