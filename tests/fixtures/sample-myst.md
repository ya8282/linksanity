# Sample MyST Document

An [inline link](https://example.com).

See {doc}`installation-guide` for setup instructions.

See also {ref}`quickstart-label` for a faster path.

This sentence mentions the doc and ref roles by name and uses a Python
dict literal such as {"a": 1}, plus a code span like `some_variable`,
but none of that is genuine MyST role syntax.

```
Example showing role syntax: {doc}`fenced-example`
```

{ref}`after-fence-label` should still be extracted.
