#version 330
uniform vec3 u_forward;
uniform vec3 u_right;
uniform vec3 u_up;
uniform vec2 u_tan;
uniform vec3 u_sun;
uniform vec3 u_top;
uniform vec3 u_horizon;
in vec2 v_ndc;
out vec4 frag;
void main() {
    vec3 dir = normalize(u_forward + u_right * (v_ndc.x * u_tan.x)
                         + u_up * (v_ndc.y * u_tan.y));
    float h = clamp(dir.y, -1.0, 1.0);
    vec3 col = mix(u_horizon, u_top,
                   pow(clamp(h, 0.0, 1.0), 0.55));
    if (h < 0.0)
        col = mix(u_horizon, vec3(0.36, 0.48, 0.59),
                  clamp(-h * 2.2, 0.0, 1.0));
    float sunDot = max(dot(dir, normalize(u_sun)), 0.0);
    col += vec3(1.0, 0.66, 0.38) * pow(sunDot, 10.0) * 0.10;
    col += vec3(1.0, 0.83, 0.61) * pow(sunDot, 48.0) * 0.20;
    col += vec3(1.0, 0.94, 0.78) * pow(sunDot, 900.0) * 1.35;
    float haze = exp(-abs(h) * 5.0) * 0.035;
    col = mix(col, vec3(0.78, 0.84, 0.91), haze);
    frag = vec4(col, 1.0);
}
