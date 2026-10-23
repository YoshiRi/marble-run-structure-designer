# Commercial Set Presets

These files describe product/set contents separately from the user's actual owned inventory.

They are useful for:

- initializing an inventory from a purchased set
- combining multiple sets
- comparing a manual count against the nominal product contents
- generating layouts constrained to a known commercial set

## Scope

Current / recently marketed Japanese presets:

- `basic-qd001.yaml`
- `funny-function-qd003.yaml`
- `twist-and-rail-qd005.yaml`
- `speedway-qd101.yaml`

Historical preset kept because it matches the user's older Twist set family:

- `historical/twist-qde6008ab05.yaml`

The bead catcher and retail bundles are not represented as standalone solver inventories because they do not add a distinct Quadrilla construction inventory.

## Confidence rules

A preset can contain both:

- **confirmed product totals** from official product pages/catalogs
- **detailed breakdowns** from secondary listings when the official page only gives aggregate counts

Such fields carry their own confidence/note instead of pretending all counts have the same provenance.

Do not copy a product preset over `catalog/inventory.yaml` blindly. The physical collection may combine multiple sets and may have missing pieces.
