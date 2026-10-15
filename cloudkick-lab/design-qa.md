# Option 1 design QA

- Source visual truth: `docs/qa/option-1-source.png`
- Browser-rendered implementation: `docs/qa/option-1-implementation-latest.png`
- Combined comparison: `docs/qa/option-1-comparison-latest.png`
- Responsive evidence: `docs/qa/option-1-mobile.png`
- Desktop viewport: 1440 × 1024 CSS pixels, device scale factor 1
- Source pixels: 1440 × 1024
- Implementation pixels: 1440 × 1024
- Mobile viewport: 390 × 844 CSS pixels, device scale factor 1
- State: signed-in C-104 customer, pending CloudRunner return proposal, secondary
  TrailStep help path visible

## Findings

No actionable P0, P1 or P2 differences remain.

- Fonts and typography: the implementation uses locally hosted Inter 400, 600 and
  700, matching the source's neutral performance-retail typography. Display hierarchy,
  compact navigation, body line height and card labels were checked at original
  resolution. Wrapping remains readable at 390 px.
- Spacing and layout rhythm: the 320 px order rail, flexible assistant panel, 18 px
  gutter, 1320 px maximum frame and compact card spacing reproduce the source's main
  proportions. The desktop page has no horizontal overflow. The mobile layout collapses
  to one column without hidden controls.
- Colors and visual tokens: deep ink header, warm off-white canvas, white surfaces,
  restrained teal states and one lime approval action match the source. Focus indicators
  and narrow-screen hero contrast remain visible.
- Image quality and asset fidelity: the wide shoe-and-mountain campaign image and both
  product cutouts are generated raster assets, not CSS drawings or placeholders. They
  remain sharp at their rendered sizes and the cutouts retain clean transparency.
- Copy and content: the retail title, signed-in identity, order summary, assistant role,
  proposal amount, explicit confirmation boundary and secondary-item help path match the
  intended state. Technical build and mode details are moved into a collapsed disclosure.
- Interaction and accessibility: URL-fragment sign-in, new conversation, safe Markdown
  rendering, message submit, structured approval hydration, confirmation, automatic
  return continuation and mobile layout were exercised in Chromium. Browser console and
  page-error capture returned no errors. The approval flow completed to `RET-ABC123` in
  the mocked browser fixture.

## Full-view comparison evidence

`docs/qa/option-1-comparison-latest.png` places the source and final browser capture
in one 2880 × 1024 image. The header, hero, two-column portal, inline return proposal,
secondary-item row, composer and collapsed Demo details align in hierarchy and state.

## Focused-region evidence

The source and implementation were also opened independently at original resolution to
check the hero crop, product cutout edges, proposal typography, £89 amount, confirmation
copy and input focus state. Separate cropped files were not needed because these regions
are legible in the original-resolution captures.

## Comparison history

1. Initial desktop pass found a P2 conversation-state mismatch: quick actions remained
   after the customer sent a free-form message. The submit path now removes them, and a
   compact TrailStep help row occupies the secondary-item position from the source.
2. Initial mobile pass found a P1 product-image overflow caused by percentage height on a
   transparent square asset, plus P2 hero-copy contrast over the mountain crop. The
   mobile image now uses an explicit 150 px contained frame and the hero uses a solid
   translucent surface. The revised 390 px capture has no horizontal overflow and the
   product no longer overlaps its details.
3. Final desktop and mobile passes found no remaining P0, P1 or P2 issues. No browser
   console errors were recorded.
4. The binary-delivery regression pass loaded the hero JPEG, both 720 × 720 WebP
   product cutouts and all local fonts in Chromium. Every image reported a non-zero
   natural width, the page had zero horizontal overflow and console/page-error capture
   was empty. API Gateway binary decoding is additionally enforced by Terraform and
   checked against the deployed URL by `smoke.py`.

## Follow-up polish

- P3: a future brand pass could replace the text wordmark with an official CloudKick
  brand asset if one is created. The present wordmark is intentionally editable text.

final result: passed
