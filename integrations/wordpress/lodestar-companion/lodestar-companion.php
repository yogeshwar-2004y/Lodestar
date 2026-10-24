<?php
/**
 * Plugin Name:       Lodestar Companion
 * Description:       Least-privilege REST endpoints that let Lodestar read and update SEO title / meta description with revision history, optimistic concurrency and safe restoration.
 * Version:           1.0.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * License:           GPL-2.0-or-later
 * Text Domain:       lodestar-companion
 */

if (!defined('ABSPATH')) {
    exit;
}

const LODESTAR_VERSION = '1.0.0';
const LODESTAR_NS = 'lodestar/v1';
const LODESTAR_CAP = 'lodestar_manage_seo';
const LODESTAR_HISTORY_META = '_lodestar_seo_history';
const LODESTAR_HISTORY_MAX = 50;

/* -------------------------------------------------------------------------
 * Activation: create a least-privilege role for the Lodestar API user.
 * ---------------------------------------------------------------------- */
register_activation_hook(__FILE__, function () {
    add_role('lodestar_seo_agent', 'Lodestar SEO Agent', array(
        'read' => true,
        'edit_posts' => true,
        'edit_pages' => true,
        'edit_others_posts' => true,
        'edit_others_pages' => true,
        'edit_published_posts' => true,
        'edit_published_pages' => true,
        LODESTAR_CAP => true,
    ));
    $admin = get_role('administrator');
    if ($admin) {
        $admin->add_cap(LODESTAR_CAP);
    }
});

register_deactivation_hook(__FILE__, function () {
    remove_role('lodestar_seo_agent');
});

/* -------------------------------------------------------------------------
 * SEO field storage adapters. We never assume every SEO plugin exposes the same
 * fields: only adapters listed here are writable.
 * ---------------------------------------------------------------------- */
function lodestar_seo_plugin() {
    if (defined('WPSEO_VERSION')) {
        return 'yoast';
    }
    if (defined('RANK_MATH_VERSION')) {
        return 'rankmath';
    }
    if (defined('AIOSEO_VERSION')) {
        return 'aioseo';
    }
    return 'none';
}

function lodestar_meta_keys($plugin) {
    switch ($plugin) {
        case 'yoast':
            return array('title' => '_yoast_wpseo_title', 'description' => '_yoast_wpseo_metadesc');
        case 'rankmath':
            return array('title' => 'rank_math_title', 'description' => 'rank_math_description');
        case 'none':
            return array('title' => '_lodestar_title', 'description' => '_lodestar_description');
        default:
            return null; // AIOSEO stores data in custom tables: read-only in V1.
    }
}

function lodestar_get_fields($post_id) {
    $keys = lodestar_meta_keys(lodestar_seo_plugin());
    if (!$keys) {
        return null;
    }
    return array(
        'title' => (string) get_post_meta($post_id, $keys['title'], true),
        'description' => (string) get_post_meta($post_id, $keys['description'], true),
    );
}

function lodestar_version($fields) {
    return substr(sha1(wp_json_encode(array($fields['title'], $fields['description']))), 0, 16);
}

/* -------------------------------------------------------------------------
 * Front-end output when no SEO plugin is active.
 * ---------------------------------------------------------------------- */
add_action('wp_head', function () {
    if (lodestar_seo_plugin() !== 'none' || !is_singular()) {
        return;
    }
    $desc = get_post_meta(get_queried_object_id(), '_lodestar_description', true);
    if ($desc !== '') {
        echo '<meta name="description" content="' . esc_attr($desc) . '" />' . "\n";
    }
}, 1);

add_filter('pre_get_document_title', function ($title) {
    if (lodestar_seo_plugin() !== 'none' || !is_singular()) {
        return $title;
    }
    $t = get_post_meta(get_queried_object_id(), '_lodestar_title', true);
    return $t !== '' ? $t : $title;
}, 20);

/* -------------------------------------------------------------------------
 * Settings: the site owner pastes the Lodestar verification token here.
 * ---------------------------------------------------------------------- */
add_action('admin_menu', function () {
    add_options_page('Lodestar', 'Lodestar', 'manage_options', 'lodestar', 'lodestar_settings_page');
});

add_action('admin_init', function () {
    register_setting('lodestar', 'lodestar_verification_token', array(
        'type' => 'string',
        'sanitize_callback' => function ($v) {
            return preg_replace('/[^A-Za-z0-9_\-]/', '', (string) $v);
        },
    ));
});

function lodestar_settings_page() {
    ?>
    <div class="wrap">
        <h1>Lodestar Companion</h1>
        <p>Detected SEO plugin: <strong><?php echo esc_html(lodestar_seo_plugin()); ?></strong></p>
        <form method="post" action="options.php">
            <?php settings_fields('lodestar'); ?>
            <table class="form-table">
                <tr>
                    <th scope="row"><label for="lodestar_verification_token">Verification token</label></th>
                    <td><input name="lodestar_verification_token" id="lodestar_verification_token" type="text" class="regular-text"
                               value="<?php echo esc_attr(get_option('lodestar_verification_token', '')); ?>"/></td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>
    </div>
    <?php
}

/* -------------------------------------------------------------------------
 * REST API
 * ---------------------------------------------------------------------- */
function lodestar_can_manage() {
    return current_user_can(LODESTAR_CAP);
}

function lodestar_can_edit_post(WP_REST_Request $req) {
    return current_user_can(LODESTAR_CAP) && current_user_can('edit_post', (int) $req['id']);
}

function lodestar_resource_payload($post) {
    $fields = lodestar_get_fields($post->ID);
    return array(
        'id' => $post->ID,
        'type' => $post->post_type,
        'status' => $post->post_status,
        'permalink' => get_permalink($post),
        'modified_gmt' => $post->post_modified_gmt,
        'seo_plugin' => lodestar_seo_plugin(),
        'writable' => $fields !== null,
        'seo' => $fields,
        'version' => $fields ? lodestar_version($fields) : null,
    );
}

add_action('rest_api_init', function () {
    register_rest_route(LODESTAR_NS, '/status', array(
        'methods' => 'GET',
        'permission_callback' => 'lodestar_can_manage',
        'callback' => function () {
            return array(
                'plugin_version' => LODESTAR_VERSION,
                'seo_plugin' => lodestar_seo_plugin(),
                'writable' => lodestar_meta_keys(lodestar_seo_plugin()) !== null,
                'site_url' => home_url('/'),
                'verification_token' => get_option('lodestar_verification_token', ''),
            );
        },
    ));

    register_rest_route(LODESTAR_NS, '/resolve', array(
        'methods' => 'GET',
        'permission_callback' => 'lodestar_can_manage',
        'args' => array('url' => array('required' => true, 'sanitize_callback' => 'esc_url_raw')),
        'callback' => function (WP_REST_Request $req) {
            $url = $req['url'];
            $id = url_to_postid($url);
            if (!$id && untrailingslashit($url) === untrailingslashit(home_url('/'))) {
                $id = (int) get_option('page_on_front');
            }
            $post = $id ? get_post($id) : null;
            if (!$post || !current_user_can('edit_post', $post->ID)) {
                return new WP_Error('lodestar_not_found', 'No editable post or page for this URL.', array('status' => 404));
            }
            return lodestar_resource_payload($post);
        },
    ));

    register_rest_route(LODESTAR_NS, '/resources', array(
        'methods' => 'GET',
        'permission_callback' => 'lodestar_can_manage',
        'callback' => function (WP_REST_Request $req) {
            $q = new WP_Query(array(
                'post_type' => array('post', 'page'),
                'post_status' => 'publish',
                'posts_per_page' => min(100, max(1, (int) ($req['per_page'] ?: 100))),
                'paged' => max(1, (int) ($req['page'] ?: 1)),
            ));
            return array('resources' => array_map('lodestar_resource_payload', $q->posts), 'total' => (int) $q->found_posts);
        },
    ));

    register_rest_route(LODESTAR_NS, '/seo/(?P<id>\d+)', array(
        array(
            'methods' => 'GET',
            'permission_callback' => 'lodestar_can_edit_post',
            'callback' => function (WP_REST_Request $req) {
                $post = get_post((int) $req['id']);
                if (!$post) {
                    return new WP_Error('lodestar_not_found', 'Not found', array('status' => 404));
                }
                return lodestar_resource_payload($post);
            },
        ),
        array(
            'methods' => 'POST',
            'permission_callback' => 'lodestar_can_edit_post',
            'callback' => 'lodestar_write_seo',
        ),
    ));

    register_rest_route(LODESTAR_NS, '/seo/(?P<id>\d+)/history', array(
        'methods' => 'GET',
        'permission_callback' => 'lodestar_can_edit_post',
        'callback' => function (WP_REST_Request $req) {
            $h = get_post_meta((int) $req['id'], LODESTAR_HISTORY_META, true);
            return array('history' => is_array($h) ? $h : array());
        },
    ));
});

function lodestar_write_seo(WP_REST_Request $req) {
    $post_id = (int) $req['id'];
    $post = get_post($post_id);
    if (!$post) {
        return new WP_Error('lodestar_not_found', 'Not found', array('status' => 404));
    }
    $plugin = lodestar_seo_plugin();
    $keys = lodestar_meta_keys($plugin);
    if (!$keys) {
        return new WP_Error('lodestar_unsupported', 'The active SEO plugin is not writable by Lodestar.', array('status' => 422));
    }
    $body = $req->get_json_params();
    $fields = isset($body['fields']) && is_array($body['fields']) ? $body['fields'] : array();
    $allowed = array_intersect_key($fields, array('title' => 1, 'description' => 1));
    if (!$allowed) {
        return new WP_Error('lodestar_invalid', 'No supported fields supplied.', array('status' => 400));
    }
    foreach ($allowed as $k => $v) {
        if (!is_string($v) || mb_strlen($v) > 400) {
            return new WP_Error('lodestar_invalid', "Invalid value for $k.", array('status' => 400));
        }
    }

    // Optimistic concurrency: refuse if the SEO fields changed since the patch was prepared.
    $current = lodestar_get_fields($post_id);
    $current_version = lodestar_version($current);
    if (!empty($body['expected_version']) && !hash_equals($current_version, (string) $body['expected_version'])) {
        return new WP_Error('lodestar_conflict', 'SEO fields changed since the patch was prepared.',
            array('status' => 409, 'current_version' => $current_version));
    }

    foreach ($allowed as $k => $v) {
        update_post_meta($post_id, $keys[$k], sanitize_text_field($v));
    }
    clean_post_cache($post_id);
    $after = lodestar_get_fields($post_id);
    $revision_id = wp_generate_uuid4();
    $history = get_post_meta($post_id, LODESTAR_HISTORY_META, true);
    $history = is_array($history) ? $history : array();
    $history[] = array(
        'revision_id' => $revision_id,
        'at' => gmdate('c'),
        'user_id' => get_current_user_id(),
        'change_ref' => sanitize_text_field((string) ($body['change_ref'] ?? '')),
        'is_rollback' => !empty($body['is_rollback']),
        'before' => $current,
        'after' => $after,
    );
    update_post_meta($post_id, LODESTAR_HISTORY_META, array_slice($history, -LODESTAR_HISTORY_MAX));

    return array(
        'id' => $post_id,
        'revision_id' => $revision_id,
        'previous' => $current,
        'seo' => $after,
        'version' => lodestar_version($after),
    );
}
