# UI UX Output Templates

## 1) Problem Statement

```md
## Problem
<What user problem is being solved?>

## Target User
<Who is this for?>

## Success Metric
<How success will be measured?>

## Constraints
<Platform, technical, or policy constraints>
```

## 2) User Flow

```md
## User Flow
1. <Entry point>
2. <Step>
3. <Decision>
4. <Outcome>

## Alternate Paths
- Empty state: <behavior>
- Error state: <behavior>
- Recovery path: <behavior>
```

## 3) Wireframe Spec

```md
## Screen: <name>
- Primary goal: <goal>
- Layout regions: <header/content/sidebar/footer>
- Main components: <list>
- Primary CTA: <action>
- Secondary actions: <actions>
```

## 4) Component + State Spec

```md
| Component | State | Trigger | Behavior | Validation/Rules |
|---|---|---|---|---|
| Search input | Error | Invalid query | Show inline error | Min 2 chars |
```

## 5) Accessibility Notes

```md
## Accessibility
- Keyboard: <tab order and shortcuts>
- Focus: <visible focus behavior>
- Labels: <aria/semantic labeling notes>
- Contrast: <expected level or token usage>
```

## 6) Engineering Handoff

```md
## Implementation Notes
- Data dependencies: <API/state dependencies>
- Edge cases: <list>
- Telemetry: <events to track>
- Open questions: <list>
```
