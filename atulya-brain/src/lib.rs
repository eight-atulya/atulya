use serde::{Deserialize, Serialize};
use std::ffi::{c_char, CStr, CString};
use std::ptr;

#[derive(Debug, Serialize, Deserialize)]
struct BrainResponse {
    ok: bool,
    message: String,
}

fn to_json_response(ok: bool, message: impl Into<String>) -> *mut c_char {
    let response = BrainResponse {
        ok,
        message: message.into(),
    };
    let json = serde_json::to_string(&response)
        .unwrap_or_else(|_| "{\"ok\":false,\"message\":\"serialization_error\"}".to_string());
    CString::new(json).map_or(ptr::null_mut(), CString::into_raw)
}

fn parse_input(ptr_in: *const c_char) -> Result<String, String> {
    if ptr_in.is_null() {
        return Err("null_input".to_string());
    }
    let c_str = unsafe { CStr::from_ptr(ptr_in) };
    c_str
        .to_str()
        .map(|s| s.to_string())
        .map_err(|_| "invalid_utf8".to_string())
}

#[no_mangle]
pub extern "C" fn atulya_brain_initialize(config_json: *const c_char) -> *mut c_char {
    match parse_input(config_json) {
        Ok(_) => to_json_response(true, "atulya-brain initialized"),
        Err(e) => to_json_response(false, e),
    }
}

#[no_mangle]
pub extern "C" fn atulya_brain_run_sub_routine(task_json: *const c_char) -> *mut c_char {
    match parse_input(task_json) {
        Ok(_) => to_json_response(true, "sub_routine executed"),
        Err(e) => to_json_response(false, e),
    }
}

#[no_mangle]
pub extern "C" fn atulya_brain_predict_activity(request_json: *const c_char) -> *mut c_char {
    match parse_input(request_json) {
        Ok(_) => to_json_response(true, "prediction complete"),
        Err(e) => to_json_response(false, e),
    }
}

#[no_mangle]
pub extern "C" fn atulya_brain_free(ptr_out: *mut c_char) {
    if ptr_out.is_null() {
        return;
    }
    unsafe {
        let _ = CString::from_raw(ptr_out);
    }
}
