"""
Theme-Presets, Farbtabellen und CSS-Variablen-Generierung für EntailsNG.
Trennt Design-Definitionen von den Django-Modellen.
"""

THEME_PRESETS = {
    'WARM_AMBER': {
        '--ink': '#2b2115',
        '--muted': '#6f6252',
        '--line': '#e7dac8',
        '--paper': '#fffaf2',
        '--panel': '#ffffff',
        '--navy': '#332719',
        '--signal': '#f8ab2d',
        '--signal-deep': '#8a4d00',
        '--signal-soft': '#fff0d2',
        '--amber': '#d97817',
        '--amber-soft': '#ffead0',
        '--sidebar-text': '#fffaf2',
        '--sidebar-nav-text': '#eadfce',
        '--sidebar-nav-hover-bg': 'rgba(255, 255, 255, 0.08)',
        '--sidebar-nav-hover-text': '#ffffff',
        '--sidebar-nav-active-bg': '#ffffff',
        '--sidebar-nav-active-text': '#332719',
        '--sidebar-border': 'rgba(255, 255, 255, 0.1)',
    },
    'CYBERPUNK': {
        '--ink': '#e2e8f0',
        '--muted': '#94a3b8',
        '--line': '#2a2d3d',
        '--paper': '#0f111a',
        '--panel': '#181b29',
        '--navy': '#0b0d14',
        '--signal': '#00f0ff',
        '--signal-deep': '#ff0055',
        '--signal-soft': 'rgba(0, 240, 255, 0.15)',
        '--amber': '#ff0055',
        '--amber-soft': 'rgba(255, 0, 85, 0.15)',
        '--sidebar-text': '#e2e8f0',
        '--sidebar-nav-text': '#94a3b8',
        '--sidebar-nav-hover-bg': 'rgba(0, 240, 255, 0.12)',
        '--sidebar-nav-hover-text': '#00f0ff',
        '--sidebar-nav-active-bg': '#00f0ff',
        '--sidebar-nav-active-text': '#0b0d14',
        '--sidebar-border': 'rgba(42, 45, 61, 0.6)',
    },
    'SLATE_BLUE': {
        '--ink': '#1e293b',
        '--muted': '#64748b',
        '--line': '#cbd5e1',
        '--paper': '#f8fafc',
        '--panel': '#ffffff',
        '--navy': '#0f172a',
        '--signal': '#3b82f6',
        '--signal-deep': '#1d4ed8',
        '--signal-soft': '#dbeafe',
        '--amber': '#2563eb',
        '--amber-soft': '#eff6ff',
        '--sidebar-text': '#f8fafc',
        '--sidebar-nav-text': '#cbd5e1',
        '--sidebar-nav-hover-bg': 'rgba(59, 130, 246, 0.15)',
        '--sidebar-nav-hover-text': '#ffffff',
        '--sidebar-nav-active-bg': '#3b82f6',
        '--sidebar-nav-active-text': '#ffffff',
        '--sidebar-border': 'rgba(255, 255, 255, 0.1)',
    },
    'EMERALD': {
        '--ink': '#111827',
        '--muted': '#4b5563',
        '--line': '#d1d5db',
        '--paper': '#f3f4f6',
        '--panel': '#ffffff',
        '--navy': '#064e3b',
        '--signal': '#10b981',
        '--signal-deep': '#047857',
        '--signal-soft': '#d1fae5',
        '--amber': '#059669',
        '--amber-soft': '#ecfdf5',
        '--sidebar-text': '#f3f4f6',
        '--sidebar-nav-text': '#a7f3d0',
        '--sidebar-nav-hover-bg': 'rgba(16, 185, 129, 0.15)',
        '--sidebar-nav-hover-text': '#ffffff',
        '--sidebar-nav-active-bg': '#10b981',
        '--sidebar-nav-active-text': '#064e3b',
        '--sidebar-border': 'rgba(255, 255, 255, 0.1)',
    },
    'QUAKE_99': {
        '--ink': '#E4E4E7',
        '--muted': '#A1A1AA',
        '--line': '#3F3F46',
        '--paper': '#18181B',
        '--panel': '#27272A',
        '--navy': '#121215',
        '--signal': '#EA580C',
        '--signal-deep': '#C2410C',
        '--signal-soft': 'rgba(234, 88, 12, 0.15)',
        '--amber': '#CA8A04',
        '--amber-soft': 'rgba(202, 138, 4, 0.15)',
        '--sidebar-text': '#E4E4E7',
        '--sidebar-nav-text': '#A1A1AA',
        '--sidebar-nav-hover-bg': 'rgba(234, 88, 12, 0.15)',
        '--sidebar-nav-hover-text': '#ffffff',
        '--sidebar-nav-active-bg': '#EA580C',
        '--sidebar-nav-active-text': '#ffffff',
        '--sidebar-border': 'rgba(255, 255, 255, 0.1)',
    },
    'ARENA_PRO': {
        '--ink': '#FFFFFF',
        '--muted': '#8892B0',
        '--line': '#222836',
        '--paper': '#0B0E14',
        '--panel': '#151922',
        '--navy': '#070A0F',
        '--signal': '#FF4655',
        '--signal-deep': '#E02B3B',
        '--signal-soft': 'rgba(255, 70, 85, 0.15)',
        '--amber': '#00E599',
        '--amber-soft': 'rgba(0, 229, 153, 0.15)',
        '--sidebar-text': '#FFFFFF',
        '--sidebar-nav-text': '#8892B0',
        '--sidebar-nav-hover-bg': 'rgba(255, 70, 85, 0.15)',
        '--sidebar-nav-hover-text': '#ffffff',
        '--sidebar-nav-active-bg': '#FF4655',
        '--sidebar-nav-active-text': '#ffffff',
        '--sidebar-border': 'rgba(255, 255, 255, 0.1)',
    },
    'CYBERDECK': {
        '--ink': '#E0E7FF',
        '--muted': '#94A3B8',
        '--line': '#2A244D',
        '--paper': '#0A0915',
        '--panel': '#121024',
        '--navy': '#06050D',
        '--signal': '#00F0FF',
        '--signal-deep': '#00B4D8',
        '--signal-soft': 'rgba(0, 240, 255, 0.15)',
        '--amber': '#FF007F',
        '--amber-soft': 'rgba(255, 0, 127, 0.15)',
        '--sidebar-text': '#E0E7FF',
        '--sidebar-nav-text': '#94A3B8',
        '--sidebar-nav-hover-bg': 'rgba(0, 240, 255, 0.12)',
        '--sidebar-nav-hover-text': '#00F0FF',
        '--sidebar-nav-active-bg': '#FF007F',
        '--sidebar-nav-active-text': '#ffffff',
        '--sidebar-border': 'rgba(255, 255, 255, 0.1)',
    },
    'MAINFRAME': {
        '--ink': '#86EFAC',
        '--muted': '#4ADE80',
        '--line': '#1A2E1C',
        '--paper': '#050805',
        '--panel': '#0C130D',
        '--navy': '#020402',
        '--signal': '#22C55E',
        '--signal-deep': '#16A34A',
        '--signal-soft': 'rgba(34, 197, 94, 0.15)',
        '--amber': '#FACC15',
        '--amber-soft': 'rgba(250, 204, 21, 0.15)',
        '--sidebar-text': '#86EFAC',
        '--sidebar-nav-text': '#4ADE80',
        '--sidebar-nav-hover-bg': 'rgba(34, 197, 94, 0.12)',
        '--sidebar-nav-hover-text': '#86EFAC',
        '--sidebar-nav-active-bg': '#22C55E',
        '--sidebar-nav-active-text': '#020402',
        '--sidebar-border': 'rgba(34, 197, 94, 0.2)',
    },
    'DAYLIGHT': {
        '--ink': '#0F172A',
        '--muted': '#64748B',
        '--line': '#E2E8F0',
        '--paper': '#F8FAFC',
        '--panel': '#FFFFFF',
        '--navy': '#0F172A',
        '--signal': '#1D4ED8',
        '--signal-deep': '#1E40AF',
        '--signal-soft': '#DBEAFE',
        '--amber': '#0284C7',
        '--amber-soft': '#E0F2FE',
        '--sidebar-text': '#F8FAFC',
        '--sidebar-nav-text': '#94A3B8',
        '--sidebar-nav-hover-bg': 'rgba(255, 255, 255, 0.08)',
        '--sidebar-nav-hover-text': '#ffffff',
        '--sidebar-nav-active-bg': '#ffffff',
        '--sidebar-nav-active-text': '#0F172A',
        '--sidebar-border': 'rgba(255, 255, 255, 0.1)',
    },
}

SCALE_MAP = {
    'XS': {
        '--font-base': '13px',
        '--font-xs': '10px',
        '--font-sm': '11px',
        '--font-md': '13px',
        '--font-lg': '15px',
        '--font-xl': '18px',
        '--font-2xl': '22px',
        '--font-3xl': '28px',
        '--sidebar': '220px',
        '--card-padding': '16px',
        '--btn-height': '34px',
        '--input-height': '36px',
        '--radius': '14px',
        '--nav-item-height': '36px',
        '--nav-font-size': '12px',
        '--nav-icon-size': '16px',
        '--nav-badge-font-size': '9px',
        '--nav-padding': '0 10px',
        '--foot-font-size': '11px',
        '--mobile-item-height': '52px',
        '--mobile-font-size': '10px',
        '--mobile-icon-size': '18px',
    },
    'SM': {
        '--font-base': '14px',
        '--font-xs': '10.5px',
        '--font-sm': '12px',
        '--font-md': '14px',
        '--font-lg': '16.5px',
        '--font-xl': '20px',
        '--font-2xl': '25px',
        '--font-3xl': '31px',
        '--sidebar': '235px',
        '--card-padding': '20px',
        '--btn-height': '38px',
        '--input-height': '39px',
        '--radius': '16px',
        '--nav-item-height': '39px',
        '--nav-font-size': '13px',
        '--nav-icon-size': '18px',
        '--nav-badge-font-size': '10px',
        '--nav-padding': '0 12px',
        '--foot-font-size': '12px',
        '--mobile-item-height': '57px',
        '--mobile-font-size': '10.5px',
        '--mobile-icon-size': '20px',
    },
    'MD': {
        '--font-base': '15px',
        '--font-xs': '11px',
        '--font-sm': '13px',
        '--font-md': '15px',
        '--font-lg': '18px',
        '--font-xl': '22px',
        '--font-2xl': '28px',
        '--font-3xl': '35px',
        '--sidebar': '246px',
        '--card-padding': '24px',
        '--btn-height': '42px',
        '--input-height': '42px',
        '--radius': '18px',
        '--nav-item-height': '42px',
        '--nav-font-size': '14px',
        '--nav-icon-size': '19px',
        '--nav-badge-font-size': '10px',
        '--nav-padding': '0 13px',
        '--foot-font-size': '13px',
        '--mobile-item-height': '62px',
        '--mobile-font-size': '11px',
        '--mobile-icon-size': '21px',
    },
    'LG': {
        '--font-base': '16px',
        '--font-xs': '12px',
        '--font-sm': '14px',
        '--font-md': '16px',
        '--font-lg': '19.5px',
        '--font-xl': '24px',
        '--font-2xl': '31px',
        '--font-3xl': '39px',
        '--sidebar': '260px',
        '--card-padding': '28px',
        '--btn-height': '46px',
        '--input-height': '45px',
        '--radius': '20px',
        '--nav-item-height': '46px',
        '--nav-font-size': '15px',
        '--nav-icon-size': '21px',
        '--nav-badge-font-size': '11px',
        '--nav-padding': '0 14px',
        '--foot-font-size': '14px',
        '--mobile-item-height': '68px',
        '--mobile-font-size': '12px',
        '--mobile-icon-size': '23px',
    },
    'XL': {
        '--font-base': '17px',
        '--font-xs': '13px',
        '--font-sm': '15px',
        '--font-md': '17px',
        '--font-lg': '21px',
        '--font-xl': '26px',
        '--font-2xl': '34px',
        '--font-3xl': '43px',
        '--sidebar': '275px',
        '--card-padding': '32px',
        '--btn-height': '50px',
        '--input-height': '48px',
        '--radius': '22px',
        '--nav-item-height': '50px',
        '--nav-font-size': '16px',
        '--nav-icon-size': '23px',
        '--nav-badge-font-size': '12px',
        '--nav-padding': '0 16px',
        '--foot-font-size': '15px',
        '--mobile-item-height': '74px',
        '--mobile-font-size': '13px',
        '--mobile-icon-size': '25px',
    },
}


def build_css_variables(theme_preset, ui_scale, primary_color=None, secondary_color=None, background_color=None):
    """
    Berechnet das vollständige Dictionary von CSS-Custom-Properties basierend auf
    Preset, UI-Skalierung und optionalen Farbüberschreibungen.
    """
    default_preset = THEME_PRESETS.get('WARM_AMBER')
    base_vars = THEME_PRESETS.get(theme_preset, default_preset).copy()

    if primary_color:
        base_vars['--signal'] = primary_color
        base_vars['--amber'] = primary_color
    if secondary_color:
        base_vars['--navy'] = secondary_color
    if background_color:
        base_vars['--paper'] = background_color

    scale_vars = SCALE_MAP.get(ui_scale, SCALE_MAP.get('MD'))
    base_vars.update(scale_vars)

    paper_hex = base_vars.get('--paper', '#fffaf2').lstrip('#')
    is_dark = False
    try:
        if len(paper_hex) == 6:
            r = int(paper_hex[0:2], 16)
            g = int(paper_hex[2:4], 16)
            b = int(paper_hex[4:6], 16)
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            is_dark = luminance < 0.5
    except Exception:
        pass

    if is_dark:
        base_vars['--warning-text'] = '#facc15'
        base_vars['--warning-bg'] = 'rgba(234, 179, 8, 0.15)'
        base_vars['--warning-border'] = 'rgba(234, 179, 8, 0.35)'
        base_vars['--info-text'] = '#38bdf8'
        base_vars['--info-bg'] = 'rgba(56, 189, 248, 0.12)'
        base_vars['--info-border'] = 'rgba(56, 189, 248, 0.3)'
    else:
        base_vars['--warning-text'] = '#b45309'
        base_vars['--warning-bg'] = 'rgba(245, 158, 11, 0.12)'
        base_vars['--warning-border'] = 'rgba(245, 158, 11, 0.35)'
        base_vars['--info-text'] = '#0369a1'
        base_vars['--info-bg'] = 'rgba(2, 132, 199, 0.08)'
        base_vars['--info-border'] = 'rgba(2, 132, 199, 0.25)'

    return base_vars
