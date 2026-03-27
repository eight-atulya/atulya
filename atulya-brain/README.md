# atulya-brain

`atulya-brain` is the Rust runtime package for `sub_routine` execution and
`.atulya` cache orchestration.

This crate is designed for embedding from the Python API service and worker path.

## License

`atulya-brain` is **not MIT licensed**.

This component is released under a **research-only, non-commercial license**.
Commercial usage is prohibited. You may not use this component to generate
commercial revenue, offer paid services, or distribute it as part of a
commercial product.

See `atulya-brain/LICENSE` for the complete license terms.

## Build

```bash
cargo build --release
```

The built dynamic library can be referenced by:

- `ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH`

## FFI Exports

- `atulya_brain_initialize(config_json)`
- `atulya_brain_run_sub_routine(task_json)`
- `atulya_brain_predict_activity(request_json)`
- `atulya_brain_free(ptr)`
