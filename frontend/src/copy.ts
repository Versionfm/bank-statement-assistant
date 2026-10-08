export const copy = {
  productName: "Bank Statement Assistant",
  eyebrow: "Private financial review",
  welcomeTitle: "Your statements, made understandable.",
  welcomeBody:
    "Import BPI statements, review every uncertain result, and understand where your money went—without sending financial data off your machine.",
  foundationNote:
    "Import is available for unencrypted, text-based PDFs. Every result remains in review until deterministic checks pass.",
  navigation: [
    "Statements",
    "Transactions",
    "Reports",
    "Rules",
    "Financial Assistant",
  ],
  privacyTitle: "Local by default",
  privacyBody:
    "Application services remain on this machine and are exposed through loopback access only.",
  evidenceTitle: "Evidence preserved",
  evidenceBody:
    "Original statement values remain immutable when later corrections are applied.",
  exactTitle: "Exact financial arithmetic",
  exactBody:
    "Money and report calculations use decimal values and deterministic validation.",
  importTitle: "Import a statement",
  importBody:
    "The source PDF stays on this machine. Duplicate files are detected by their content hash.",
} as const;
