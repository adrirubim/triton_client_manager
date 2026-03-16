# MODELS

Index and conventions for **model documentation**.

Model‑specific “Model Cards” live under `docs/models/` and are intended to be
kept in sync with the corresponding Triton model repositories under
`infra/models/`.

---

## Current model cards

- [`YOLO_N_INT8`](models/YOLO_N_INT8.md) – INT8‑quantised YOLO model for
  real‑time object detection.

---

## Creating a new Model Card

1. **Create / update the Triton model repo** under `infra/models/MODEL_NAME/`
   (typically via `tcm model scaffold`).
2. **Create a new card** in `docs/models/MODEL_NAME.md` based on
   `docs/models/TEMPLATE_MODEL_CARD.md`.
3. Ensure the card documents at least:

   - Purpose and expected usage.
   - Format and location (config + weights).
   - Inputs/outputs (names, dtypes, shapes).
   - Example WebSocket payload (`/ws`) and a simplified response.

4. Add the new card to the list above in this file.

