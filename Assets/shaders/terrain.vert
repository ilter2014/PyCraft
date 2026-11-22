#version 330
in vec3 in_pos;
in vec2 in_uv;
in float in_shade;
in float in_flex;
uniform mat4 u_vp;
uniform float u_time;
uniform int u_anim_mode;
uniform vec2 u_wind_dir;
out vec2 v_uv;
out float v_shade;
out vec3 v_world;
out float v_wave_height;
out float v_anim_alpha;
out float v_flex;
out vec3 v_water_normal;
out float v_water_crest;

void gerstnerWater(vec2 xz, float t, out vec3 P, out vec3 N, out float height, out float crest) {
    const float PI2 = 6.28318530718;
    const float wavelengths[8] = float[8](14.0, 9.0, 6.0, 4.0, 2.8, 1.9, 1.25, 0.85);
    const float amplitudes[8] = float[8](0.145, 0.105, 0.075, 0.050, 0.032, 0.020, 0.012, 0.007);
    const float spreads[8] = float[8](-0.52, -0.36, -0.21, -0.07, 0.08, 0.23, 0.39, 0.55);
    vec2 wind = normalize(u_wind_dir);
    vec2 crossWind = vec2(-wind.y, wind.x);
    P = vec3(xz.x, 0.0, xz.y);
    vec3 tangent = vec3(1.0, 0.0, 0.0);
    vec3 binormal = vec3(0.0, 0.0, 1.0);
    height = 0.0;
    crest = 0.0;

    for (int i = 0; i < 8; ++i) {
        float k = PI2 / wavelengths[i];
        float A = amplitudes[i];
        float angle = spreads[i];
        vec2 D = normalize(wind * cos(angle) + crossWind * sin(angle));
        float omega = sqrt(9.81 * k) * 0.58;
        float phase = k * dot(D, xz) - omega * t;
        float s = sin(phase);
        float c = cos(phase);
        float Q = min(0.82 / (k * A * 8.0), 1.0);
        float QAk = Q * A * k;

        P.x += Q * A * D.x * c;
        P.z += Q * A * D.y * c;
        P.y += A * s;
        height += A * s;
        crest += QAk * s;

        tangent.x -= QAk * D.x * D.x * s;
        tangent.y += A * k * D.x * c;
        tangent.z -= QAk * D.x * D.y * s;
        binormal.x -= QAk * D.x * D.y * s;
        binormal.y += A * k * D.y * c;
        binormal.z -= QAk * D.y * D.y * s;
    }
    N = normalize(cross(binormal, tangent));
    if (N.y < 0.0) N = -N;
    crest = clamp(crest, 0.0, 1.0);
}

void main() {
    vec3 p = in_pos;
    v_wave_height = 0.0;
    v_anim_alpha = 1.0;
    v_flex = in_flex;
    v_water_normal = vec3(0.0, 1.0, 0.0);
    v_water_crest = 0.0;
    vec2 wind = normalize(u_wind_dir);
    vec2 crossWind = vec2(-wind.y, wind.x);

    if (u_anim_mode == 1) {
        // One shared wind field; the base of each plant remains anchored.
        float phase = dot(p.xz, wind) * 0.105;
        float gustA = sin(u_time * 0.43 + phase);
        float gustB = sin(u_time * 0.27 + dot(p.xz, crossWind) * 0.073 + 1.7);
        float flutter = sin(u_time * 1.18 + dot(p.xz, wind + crossWind * 0.7) * 0.29) * 0.20;
        float flex = in_flex * in_flex;
        float sway = (gustA * 0.58 + gustB * 0.30 + flutter) * 0.17 * flex;
        p.xz += wind * sway + crossWind * (flutter * 0.035 * flex);
    }

    if (u_anim_mode == 3) {
        float fall = fract(u_time * 0.075 + in_flex);
        float drift = sin(u_time * 1.35 + in_flex * 31.0);
        p.y -= fall * 4.2;
        p.xz += wind * (drift * 0.42 * fall);
        p.xz += crossWind * (cos(u_time * 1.05 + in_flex * 19.0) * 0.32 * fall);
        v_anim_alpha = 1.0 - smoothstep(0.78, 0.99, fall);
    }

    if (u_anim_mode == 2) {
        vec3 waveP, waveN;
        float waveH, waveCrest;
        gerstnerWater(in_pos.xz, u_time, waveP, waveN, waveH, waveCrest);
        float weight = clamp(in_flex, 0.0, 1.0);
        p = mix(in_pos, waveP, weight);
        v_water_normal = waveN;
        v_wave_height = waveH;
        v_water_crest = waveCrest;
    }

    v_uv = in_uv;
    v_shade = in_shade;
    v_world = p;
    gl_Position = u_vp * vec4(p, 1.0);
}
