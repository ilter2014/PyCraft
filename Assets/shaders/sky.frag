#version 330

// Procedural sky: gradient + sun disc/glow + 2D fbm clouds + far mountain
// silhouettes. Rendered both as the real background and into the mirror
// (reflection) pass, so it is what the water mostly reflects.

in vec2 v_uv;
in vec2 v_ndc;
out vec4 frag;

uniform vec3 u_forward;
uniform vec3 u_right;
uniform vec3 u_up;
uniform vec2 u_tan;

uniform vec3 u_sun_dir;
uniform vec3 u_sun_color;
uniform float u_sun_intensity;
uniform float u_disc_bright;

uniform vec3 u_zenith;
uniform vec3 u_horizon;
uniform vec3 u_haze;
uniform vec3 u_below;

uniform vec2 u_cloud_offset;
uniform float u_cloud_coverage;
uniform float u_cloud_scale;

uniform vec3 u_ridge_far;
uniform vec3 u_ridge_near;

// ---------------------------------------------------------------- noise
float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; i++) {
        v += a * vnoise(p);
        p = p * 2.03 + vec2(17.3, 9.1);
        a *= 0.5;
    }
    return v; // ~0..1
}

float fbm1(float x, float seed) {
    return fbm(vec2(x, seed)) * 2.0 - 1.0; // ~-1..1
}

// ---------------------------------------------------------------- main
void main() {
    vec3 dir = normalize(u_forward + u_right * (v_ndc.x * u_tan.x)
                         + u_up * (v_ndc.y * u_tan.y));

    // Base gradient.
    float h = clamp(dir.y, 0.0, 1.0);
    vec3 col = mix(u_horizon, u_zenith, smoothstep(0.02, 0.32, h));

    // Warm haze band hugging the horizon, strongest near the sun azimuth.
    float flat_sd = max(dot(normalize(dir.xz), normalize(u_sun_dir.xz)), 0.0);
    col = mix(col, u_haze, exp(-h * 26.0) * (0.15 + 0.50 * pow(flat_sd, 1.5)));

    // Sun glow + disc.
    float sd = dot(dir, u_sun_dir);
    float glow = pow(max(sd, 0.0), 420.0) * 3.0
               + pow(max(sd, 0.0), 60.0) * 0.10
               + pow(max(sd, 0.0), 9.0) * 0.025;
    col += u_sun_color * u_sun_intensity * glow;
    float disc = smoothstep(0.99985, 0.99995, sd);
    col += u_sun_color * u_sun_intensity * u_disc_bright * disc;

    // Clouds on a virtual plane above the viewer.
    if (dir.y > 0.004) {
        float cloud_height = max(dir.y, 0.085);
        vec2 cp = dir.xz / cloud_height * 1800.0 * u_cloud_scale + u_cloud_offset;
        cp *= vec2(1.0, 1.35);
        float base = fbm(cp);
        float d = base - (1.0 - u_cloud_coverage);
        float alpha = smoothstep(0.0, 0.30, d) * smoothstep(0.035, 0.19, dir.y);
        alpha *= 0.92;

        // Cheap self-shadowing: sample noise shifted along the sun.
        vec2 sdir = u_sun_dir.xz * (0.8 / max(u_sun_dir.y, 0.10));
        float lit = fbm(cp + sdir * 0.55);
        float ld = clamp(0.5 + (lit - base) * 1.6, 0.0, 1.0);

        vec3 shadow_col = u_haze * 0.62 + vec3(0.10, 0.12, 0.15);
        vec3 lit_col = mix(u_sun_color, vec3(1.0, 0.91, 0.82), 0.20) * 0.78;
        vec3 ccol = mix(shadow_col, lit_col, ld);

        // Silver lining near the sun.
        float rim = pow(max(sd, 0.0), 10.0);
        ccol += u_sun_color * rim * ld * 0.8;

        col = mix(col, ccol, alpha);
    }

    // Keep the horizon clean: the old procedural ridge masks produced dark,
    // jagged cutouts against distant terrain. Atmospheric haze now blends the
    // sky naturally into the world instead.

    // Below the horizon: mirror rays only; dark fallback, blended into the
    // horizon colour at the boundary so no hard line appears at the far
    // water's mirror-horizon row.
    if (dir.y < 0.0) {
        vec3 below = mix(u_haze * 0.72, u_horizon * 0.88, exp(-abs(dir.y) * 18.0));
        // Smooth atmospheric continuation for reflected rays; avoid a black
        // lower band at the horizon in the water reflection.
        col = mix(below, u_horizon, exp(-abs(dir.y) * 42.0));
    }

    frag = vec4(col, 1.0);
}
