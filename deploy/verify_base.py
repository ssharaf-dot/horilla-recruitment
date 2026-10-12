"""Fail the image build if a different/modified Horilla baseline is supplied."""

import hashlib
from pathlib import Path

EXPECTED = {
    "horilla/settings.py": "677735769d522af5fe967033fd8604f9c305990887ce9151315e4636a7dc8483",
    "horilla/config.py": "929371454bfb958fd7147809e2bb2ee6a650347c078410b106b222ac9a293ba4",
    "base/templatetags/horillafilters.py": "1933f2fc3132fd6401799c9eb7e0e039191fb9946a41615c49bfdecb5e8a9a76",
    "base/templates/base/general_settings.html": "ae6cbcef31098726eb193ce3267727b230c6c927eb2186b7d0ce7769237b59ad",
    "templates/settings.html": "7fb11206616ad8ce51d572f7dec1f5b47f488f5fd81d05e9232f312f64f69513",
    "templates/sidebar.html": "e72b312e6b797c2b79c5d05150485891345db846aaffcf78e17bf1d55347dae3",
    "templates/floating_button.html": "a7bd4e1a8ab972c88253fa989fca96adfb3744ec548b86539cc0c201f66924bf",
    "employee/templates/employee/view/individual.html": "542fbcdde8a7a4ead2ec940cce984815449dc4ea880805741ff3d7a6a7094273",
    "employee/templates/employee_nav.html": "83a43a31c0bfeaf71fa7bb45eb59d3cf6d9f26d935fde2aa4a2484a66cf5d044",
    'horilla/urls.py': 'c06fe732c8a0ddf397df6fe273a564e4ff74e3db650800fa29237b314bacd60c',
    'horilla/horilla_middlewares.py': '760bd25989b9014c7fcf057fc6aa6a4b4a0df4f5636f7be20f7e68cd9a540109',
    'recruitment/views/dashboard.py': 'd0d9880135c177f5b218ee9d734f75ad9c5e536d74d236ed5febfefd9baf4cde',
    'recruitment/views/surveys.py': 'e22262def64ebcfc9bbc3c380c8830c46546b12945edb1c1ec0f0ae8ef5d3e4d',
    'templates/index.html': '4aaefd5f9915a78ecf6e27c2deb7b1666215461e89820e9448722705bc141096',
    'templates/login.html': '0b4f944aa03d9b07623a230c90feca782b13165f04108beb2eea4b95667254c0',
    'recruitment/templates/recruitment/nav.html': 'bfea4fa01c0128c050a452886cffc081f0bab3dc8a9be8393534a1e6ecc2d130',
    'recruitment/templates/pipeline/nav.html': 'a5f5d3b7fbf89a27ce9b11cc93da050c55dd4a3b896e3c48a2920b108d51fec4',
    'recruitment/templates/candidate/success.html': '8d92ab48ee185351a1c2242d3569f0dcbeea4c828a0fc06f4854bbb147df6296',
    'recruitment/templates/survey/candidate_survey_form.html': '2e2c323f713df8777c30e7963bdfc1baa21f4f881cb5c80564031a5c1479ce91',
}


def verify(root):
    for name, expected in EXPECTED.items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit("Unexpected baseline source: " + name)


if __name__ == "__main__":
    verify(Path("/app"))
