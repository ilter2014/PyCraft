#version 330
uniform sampler2D u_tex;
uniform vec3 u_cam;
uniform vec3 u_fog;
uniform vec2 u_fog_range;
uniform vec3 u_sun_dir;
uniform vec2 u_wind_dir;
uniform sampler2D u_scene_color;
uniform sampler2D u_water_reflection;
uniform vec2 u_screen;
uniform mat4 u_refl_vp;
uniform float u_time;
uniform int u_anim_mode;
uniform int u_cutout;
uniform float u_alpha;
uniform vec2 u_uv_offset;
in vec2 v_uv;
in float v_shade;
in vec3 v_world;
in float v_wave_height;
in float v_anim_alpha;
in float v_flex;
in vec3 v_water_normal;
in float v_water_crest;
out vec4 frag;

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float noise21(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

void main() {
    vec4 tex = texture(u_tex, v_uv + u_uv_offset);
    if (u_cutout == 1 && tex.a < 0.5) discard;

    vec3 normal = normalize(cross(dFdx(v_world), dFdy(v_world)));
    if (!gl_FrontFacing) normal = -normal;
    vec3 sunDir = normalize(u_sun_dir);
    vec3 viewDir = normalize(u_cam - v_world);

    if (u_anim_mode == 2 && v_flex > 0.5 && abs(normal.y) > 0.55) {
        vec3 geoN = normalize(v_water_normal);
        if (geoN.y < 0.0) geoN = -geoN;

        // Small wind-driven ripples enrich the geometric Gerstner normals.
        vec2 wind = normalize(u_wind_dir);
        vec2 p = v_world.xz;
        float rippleA = noise21(p * 2.2 + wind * u_time * 0.62);
        float rippleB = noise21(p * 4.8 - wind * u_time * 0.91);
        vec3 N = normalize(geoN + vec3((rippleA - 0.5) * 0.18,
                                       0.0,
                                       (rippleB - 0.5) * 0.18));

        float NoV = clamp(dot(N, viewDir), 0.001, 1.0);
        float fresnel = 0.02 + 0.98 * pow(1.0 - NoV, 5.0);
        vec2 screenUV = gl_FragCoord.xy / max(u_screen, vec2(1.0));
        vec2 refractOffset = vec2(N.x, -N.z) * (0.004 + (1.0 - NoV) * 0.012);
        vec3 refracted = texture(u_scene_color,
                                 clamp(screenUV + refractOffset, vec2(0.001), vec2(0.999))).rgb;

        // Project the actual water world position through the mirrored camera.
        vec4 reflClip = u_refl_vp * vec4(v_world, 1.0);
        vec2 reflUV = reflClip.xy / max(reflClip.w, 0.0001) * 0.5 + 0.5;
        vec3 reflected = texture(u_water_reflection,
                                 clamp(reflUV, vec2(0.001), vec2(0.999))).rgb;
        if (reflClip.w <= 0.0 || any(lessThan(reflUV, vec2(0.0))) ||
            any(greaterThan(reflUV, vec2(1.0)))) {
            reflected = mix(u_fog * 0.82, vec3(0.08, 0.17, 0.24),
                            clamp(N.y, 0.0, 1.0));
        }

        vec3 deepWater = vec3(0.006, 0.045, 0.064);
        vec3 col = mix(refracted, reflected, clamp(fresnel * 0.94 + 0.025, 0.0, 1.0));
        col = mix(col, deepWater, 0.12 + 0.08 * (1.0 - clamp(v_wave_height + 0.5, 0.0, 1.0)));

        // GGX-like sun glints follow the animated surface normal.
        vec3 halfDir = normalize(sunDir + viewDir);
        float NoL = max(dot(N, sunDir), 0.0);
        float NoH = max(dot(N, halfDir), 0.0);
        float VoH = max(dot(viewDir, halfDir), 0.0);
        float rough = 0.16;
        float a = rough * rough;
        float a2 = a * a;
        float denom = NoH * NoH * (a2 - 1.0) + 1.0;
        float D = a2 / max(3.14159265 * denom * denom, 0.0001);
        float k = (rough + 1.0) * (rough + 1.0) / 8.0;
        float Gv = NoV / (NoV * (1.0 - k) + k);
        float Gl = NoL / (NoL * (1.0 - k) + k);
        float F = 0.02 + 0.98 * pow(1.0 - VoH, 5.0);
        float specular = D * Gv * Gl * F / max(4.0 * NoV * NoL, 0.001);
        col += vec3(1.0, 0.79, 0.56) * specular * NoL * 0.34;

        // Broken crest foam: noise prevents a uniform white outline.
        float n1 = noise21(v_world.xz * 1.8 + wind * u_time * 0.16);
        float n2 = noise21(v_world.xz * 4.3 - wind * u_time * 0.22);
        float foamNoise = n1 * 0.62 + n2 * 0.38;
        float crest = smoothstep(0.30, 0.76,
                                 v_water_crest + (foamNoise - 0.5) * 0.42);
        crest *= smoothstep(0.08, 0.62, v_wave_height + 0.12);
        vec3 foamColor = mix(vec3(0.66, 0.78, 0.78),
                             vec3(0.96, 0.95, 0.87),
                             max(dot(N, sunDir), 0.0) * 0.62);
        col = mix(col, foamColor, crest * 0.66);

        float distanceToCamera = distance(v_world, u_cam);
        float fog = smoothstep(u_fog_range.x, u_fog_range.y, distanceToCamera);
        col = mix(col, u_fog, fog * 0.82);
        frag = vec4(max(col, vec3(0.0)), 1.0);
        return;
    }

    float ndl = max(dot(normal, sunDir), 0.0);
    float skyFill = 0.43 + 0.16 * clamp(normal.y, 0.0, 1.0);
    float lighting = clamp(skyFill + ndl * 0.55, 0.38, 1.12);
    vec3 col = tex.rgb * v_shade * lighting;
    float groundBounce = exp(-max(v_world.y, 0.0) * 0.032);
    col += vec3(0.060, 0.038, 0.020) * groundBounce
           * (1.0 - max(normal.y, 0.0)) * tex.rgb;
    if (u_anim_mode == 1) {
        float backLight = max(dot(-normal, sunDir), 0.0);
        col += tex.rgb * vec3(0.10, 0.15, 0.055) * backLight;
    }
    float d = distance(v_world, u_cam);
    float heightFog = smoothstep(42.0, 115.0, d) * 0.16;
    float f = clamp(smoothstep(u_fog_range.x, u_fog_range.y, d) + heightFog, 0.0, 1.0);
    col = mix(col, u_fog, f);
    col += vec3((hash21(gl_FragCoord.xy + floor(u_time * 2.0)) - 0.5) / 255.0);
    frag = vec4(max(col, vec3(0.0)), tex.a * u_alpha * v_anim_alpha);
}
