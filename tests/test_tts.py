from translator_app.tts import _device_guid, _lcids


def test_sapi_multiple_language_ids_are_split():
    assert _lcids("0411;0409") == {"411", "409"}


def test_audio_output_matching_uses_final_guid():
    value = (
        r"HKEY_LOCAL_MACHINE\Audio\{0.0.0.00000000}."
        r"{3D488D95-E2C6-4D0F-833B-3F525310D6B0}"
    )
    assert _device_guid(value) == "{3d488d95-e2c6-4d0f-833b-3f525310d6b0}"
