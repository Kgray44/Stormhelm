# Stormhelm Glass Field And Mode Commands Design

## Goal

Replace the current abstract oval-and-circle background treatment with a more faithful old-ship glass field, and add local `/deck` and `/ghost` mode commands so Stormhelm can deepen or recede without routing those intents through the core assistant flow.

## Scope

This pass includes:

- a fresh QML background built around sea-worn glass rather than abstract shape overlays
- Ghost vs Deck material depth tuned from the same shared field
- subtle ShaderEffect-driven refraction and warping
- restrained blur/distortion enhancement over the Windows material layer
- local UI command handling for `/deck` and `/ghost`
- verification that Ghost remains minimal and Deck becomes more materially pronounced

This pass explicitly excludes:

- voice pipeline work
- new tools or broader orchestration power
- changes to safety policy
- screen-awareness features
- large layout restructuring unrelated to the field and mode commands

## Recommended Approach

### Option A: Material-first shared glass field with local UI mode commands

Pros:

- best match for the Design Book and Layout Spec
- keeps Ghost and Deck as the same presence at different depths
- removes the current "stylized UI art" look
- keeps mode transitions local and immediate

Cons:

- requires careful tuning so the field reads as glass rather than fog or wallpaper
- adds some QML/ShaderEffect complexity

### Option B: Static glass texture overlay with light animation

Pros:

- faster to implement
- lower rendering complexity

Cons:

- risks looking pasted-on or fake
- weaker continuity between Ghost and Deck
- less adaptive motion language

### Option C: Full shader-heavy visual field with aggressive distortion

Pros:

- can produce the richest glass effect

Cons:

- high risk of drifting into flashy sci-fi behavior
- more fragile across packaging/runtime environments
- unnecessary complexity for this phase

## Decision

Choose Option A.

Stormhelm should feel like the screen is being viewed through a weathered command medium, not decorated by floating shapes. A material-first field gives the right identity while keeping the transition philosophy intact. `/deck` and `/ghost` should be intercepted locally in the UI so they behave like posture changes, not assistant requests.

## System Design

### Background Field

The background should become one continuous old-ship glass layer rather than a composition of large circles, ellipses, and radial washes.

The field should be built from:

- a dark tinted base veil
- faint pane variation and sea-worn tonal drift
- restrained chart-line residue and subtle structural weathering
- ShaderEffect-driven refraction/displacement that gently alters what is behind Stormhelm
- soft motion that suggests marine pressure and glass thickness, not animated wallpaper

The visual result should imply:

- old command glass
- slight optical inconsistency
- soft blur and distortion
- filtered reality beneath the interface

The field must not imply:

- decorative floating bubbles
- neon hologram panels
- broken or shattered glass
- abstract circular hero art

### Ghost Mode Material Rules

Ghost should remain extremely minimal.

Ghost mode field behavior:

- keep the desktop highly readable behind the veil
- use only light tinting
- use a small amount of blur
- use very restrained refraction
- keep surface patterning faint and sparse

Ghost should feel like the world has shifted slightly into Stormhelm's awareness.

### Command Deck Material Rules

Deck should feel like the same field deepening.

Deck mode field behavior:

- darken the veil noticeably, but keep the real world visible behind it
- strengthen blur and distortion modestly
- make the glass texture and pane drift more apparent
- allow the refraction field to feel deeper and more structural

Deck should feel like a hidden bridge emerging through thicker command glass, not a new page replacing Ghost.

### Motion Rules

The field motion should be subtle and continuous.

Primary motion sources:

- slow refraction drift
- slight warping variation over time
- faint marine pressure or caustic movement

Rules:

- no visible looping gimmick
- no large shape sweeps
- no decorative orbital background objects
- no aquarium effect

### Shader Strategy

Use a restrained ShaderEffect layer inside the QML background to drive:

- small UV displacement
- gentle horizontal and vertical waviness
- uneven glass thickness feel

The shader should support a single progression input tied to Ghost vs Deck depth so the same effect can stay faint in Ghost and deepen in Deck.

If a specific rendering backend cannot support the full effect cleanly, the field should degrade gracefully to a static tinted glass layer plus Windows blur rather than failing visually.

### Windows Material Layer

Keep the existing Windows composition helper as the OS-level support layer.

Responsibilities:

- provide platform blur/acrylic support
- reinforce the sense of filtered real content behind the window

The Python helper should remain supportive, not identity-defining. The QML field carries the visual language; the Windows layer enhances it.

### Local Mode Commands

`/deck` and `/ghost` should be intercepted in the UI controller before normal message send.

Behavior:

- `/deck` immediately transitions Stormhelm into Deck mode
- `/ghost` immediately returns Stormhelm to Ghost mode
- neither command is sent to the core chat endpoint
- each command should set a brief local status line confirming the posture change

These commands are local shell controls, not assistant requests.

### Command Parsing Boundaries

The interception layer should stay minimal and explicit.

In scope now:

- exact match `/deck`
- exact match `/ghost`

Not in scope now:

- broad slash-command framework
- aliases beyond what is required
- command execution routed through tools

### Testing

This pass should include focused verification for:

- local mode command interception
- Ghost command does not call the chat client
- Deck command does not call the chat client
- background/QML shell still loads successfully
- Ghost input path still works after the field rebuild

Visual verification should be manual for:

- Ghost remains minimal
- Deck field is more materially pronounced
- the world behind Stormhelm reads through glass rather than through abstract UI art

## Implementation Notes

Primary files likely involved:

- `C:\Stormhelm\assets\qml\components\StormBackground.qml`
- `C:\Stormhelm\assets\qml\Main.qml`
- `C:\Stormhelm\src\stormhelm\ui\controllers\main_controller.py`
- `C:\Stormhelm\src\stormhelm\ui\windows_effects.py`
- UI tests covering controller/bridge behavior

The preferred implementation direction is correction, not expansion:

- remove the large oval/circle field elements
- replace them with a single shared glass medium
- preserve the current Ghost-to-Deck continuity and anchor behavior

## Success Criteria

This pass succeeds when:

- the old abstract shape language is gone from the background
- Ghost looks like a very light command veil over the real desktop
- Deck looks like the same veil deepened into pronounced ship-glass material
- distortion and blur are visible but restrained
- `/deck` and `/ghost` switch modes instantly and locally
- the current working Ghost input behavior remains intact
