```markdown
# Design System Specification

## 1. Overview & Creative North Star: "The Kinetic Terminal"
This design system is engineered to feel like a high-precision instrument rather than a standard web application. Our Creative North Star is **The Kinetic Terminal**—an aesthetic that blends the raw, data-driven authority of a Bloomberg Terminal with the sleek, editorial sophistication of a luxury timepiece.

To move beyond "standard" dark mode, we reject the rigid, boxed-in layouts of traditional fintech. Instead, we utilize intentional asymmetry, overlapping data layers, and a hierarchy driven by light and depth rather than lines. This is a "living" interface where the AI’s intelligence is felt through subtle motion and tonal shifts.

---

## 2. Colors & Surface Philosophy
The palette is rooted in a "Deep Space" foundation, using high-chroma signals for market movements.

### The Foundation
*   **Base (Surface Lowest):** `#0b0e14` – The absolute void. Used for the primary background.
*   **Surface (Card):** `#111520` – The secondary layer for main content containers.
*   **Primary (Action):** `primary_container` (#5b8def) – Reserved for high-priority AI interactions.
*   **Success (Buy/Up):** `secondary_container` (#02d4a1) – High-contrast "Up" signal.
*   **Error (Sell/Down):** `tertiary_container` (#fd526f) – High-contrast "Down" signal.

### The "No-Line" Rule
Standard UI relies on 1px borders to separate content. **In this system, explicit 1px solid borders for sectioning are prohibited.** 
Boundaries must be defined through background shifts. For instance, a `surface_container_low` widget sits on a `surface_container_lowest` background. The change in hex value is the boundary.

### Signature Textures & Glass
*   **Tonal Transitions:** Use subtle gradients for primary CTAs, transitioning from `primary` (#aec6ff) to `primary_container` (#5b8def) at a 135° angle.
*   **Glassmorphism:** Floating overlays (modals, hover cards) must use a semi-transparent `surface_container` with a `20px` backdrop-blur to maintain the "Kinetic" feel.

---

## 3. Typography: The Narrative & The Truth
We use a dual-font strategy to separate UI narrative from raw financial data.

*   **Inter (The UI Narrative):** Used for all headlines, titles, and body copy. It provides a human-centric, readable balance to the data.
    *   *Headline-LG (#e1e2eb):* 2rem, tight letter spacing (-0.02em) for an editorial feel.
*   **JetBrains Mono (The Truth):** Every number, ticker symbol, and percentage must be rendered in JetBrains Mono. This conveys technical precision and "agentic" speed.
    *   *Data-Density:* Use `label-md` (0.75rem) in Mono for secondary metrics to allow for high information density without clutter.

---

## 4. Elevation & Depth: Tonal Layering
We achieve hierarchy by "stacking" tones. Imagine the UI as physical sheets of dark glass.

*   **The Layering Principle:** 
    1.  **Level 0:** `surface_container_lowest` (#0b0e14) - The canvas.
    2.  **Level 1:** `surface_container` (#1d2026) - Main dashboard widgets.
    3.  **Level 2:** `surface_container_highest` (#32353c) - Active states or popped-out data points.
*   **Ambient Shadows:** For floating elements, use extra-diffused shadows. 
    *   *Token:* `0px 12px 32px rgba(0, 0, 0, 0.4)`. The shadow color is never grey; it is a deeper version of the background.
*   **The "Ghost Border" Fallback:** If accessibility requires a border, use the `outline_variant` token (#424752) at **20% opacity**. It should be felt, not seen.

---

## 5. Components

### Buttons & Interaction
*   **Primary:** Background: `primary_container` (#5b8def); Text: `on_primary_container` (#00275e). 12px radius. Use a subtle glow on hover.
*   **Buy/Sell Actions:** Use `secondary_container` and `tertiary_container` respectively. These are the only components allowed to use high-saturation backgrounds.
*   **Tertiary (Ghost):** No background, `on_surface_variant` text. 

### Input Fields & Controls
*   **Text Inputs:** Background: `surface_container_low`. Radius: 10px. Focus state: 1px "Ghost Border" using `primary`.
*   **Checkboxes/Radios:** Use `primary` (#aec6ff) for the active state. Forbid standard browser styling.
*   **Chips:** 6px radius. Use `surface_container_high` for background. For filter chips, use `secondary_fixed_dim` text when active.

### Data Displays (Fintech Specific)
*   **The Ticker Card:** Forbid divider lines. Separate "Price," "Change," and "Volume" using `24px` horizontal spacing. 
*   **AI Confidence Gauges:** Use 12px rounded bars. The "filled" portion uses a gradient of `primary` to `info_action`.
*   **Lists:** Forbid dividers. Use a `1px` vertical gap between list items, letting the `background` (#10131a) act as the separator.

---

## 6. Do's and Don'ts

### Do:
*   **Do** use JetBrains Mono for every single numerical value.
*   **Do** favor vertical whitespace over horizontal lines.
*   **Do** use `surface_bright` (#363940) for hover states on dark cards to create a "lift" effect.
*   **Do** ensure all "Buy" signals use the `secondary` green (#46f1bc) for maximum legibility against the dark base.

### Don't:
*   **Don't** use pure #000000 or mid-grey. Only use the defined surface tokens.
*   **Don't** use 100% opaque borders to separate content. Use the "No-Line" rule.
*   **Don't** mix fonts. Numbers are *never* Inter; UI labels are *never* Mono.
*   **Don't** use standard shadows. If an element needs to pop, use tonal elevation (moving from `surface` to `surface_bright`).

---

**Director’s Note:** Junior designers should focus on the *density* of information. In a professional fintech tool, the user wants clarity, not emptiness. Use the 10px/12px radius scale to keep the UI feeling "approachable" but the "Deep Dark" theme to keep it "authoritative."```