import { createTheme } from '@mui/material/styles'

const talosTheme = createTheme({
  palette: {
    primary: {
      main: '#C4913A',
      dark: '#A27628',
      light: '#FDF6EC',
      contrastText: '#FFFFFF',
    },
    secondary: {
      main: '#6B6966',
      dark: '#1C1B1A',
      light: '#9C9893',
    },
    error: {
      main: '#C4462A',
      light: '#FDF0ED',
      dark: '#A33820',
    },
    warning: {
      main: '#D4940A',
      light: '#FEF9EC',
      dark: '#8C6307',
    },
    success: {
      main: '#3D8C5C',
      light: '#EFF7F2',
      dark: '#2D6944',
    },
    info: {
      main: '#2E8B8B',
      light: '#EDF7F7',
      dark: '#1F6B6B',
    },
    background: {
      default: '#F9F8F6',
      paper: '#FFFFFF',
    },
    text: {
      primary: '#1C1B1A',
      secondary: '#6B6966',
      disabled: '#C4C0BB',
    },
    divider: 'rgba(28, 27, 26, 0.10)',
  },
  typography: {
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    h1: { fontSize: '36px', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: '42px' },
    h2: { fontSize: '28px', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: '34px' },
    h3: { fontSize: '22px', fontWeight: 600, letterSpacing: '-0.02em', lineHeight: '28px' },
    h4: { fontSize: '18px', fontWeight: 600, letterSpacing: '-0.02em', lineHeight: '26px' },
    h5: { fontSize: '15px', fontWeight: 600, lineHeight: '24px' },
    h6: { fontSize: '13px', fontWeight: 600, lineHeight: '18px' },
    body1: { fontSize: '14px', fontWeight: 400, lineHeight: '22px' },
    body2: { fontSize: '13px', fontWeight: 400, lineHeight: '18px' },
    caption: { fontSize: '12px', fontWeight: 400, lineHeight: '16px' },
    overline: {
      fontSize: '11px', fontWeight: 600, lineHeight: '16px',
      letterSpacing: '0.06em', textTransform: 'uppercase',
    },
    button: { fontSize: '14px', fontWeight: 500, textTransform: 'none' },
  },
  shape: {
    borderRadius: 6,
  },
  spacing: 4,
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: '6px',
          boxShadow: 'none',
          textTransform: 'none',
          fontWeight: 500,
          '&:hover': { boxShadow: '0 1px 3px rgba(28,27,26,0.06)' },
        },
        sizeMedium: { height: '36px', padding: '0 16px' },
        sizeSmall: { height: '28px', padding: '0 8px', fontSize: '12px' },
        sizeLarge: { height: '44px', padding: '0 20px', fontSize: '15px' },
        containedPrimary: {
          backgroundColor: '#C4913A',
          '&:hover': { backgroundColor: '#B3832F' },
          '&:active': { backgroundColor: '#A27628' },
        },
        outlined: {
          borderColor: 'rgba(28,27,26,0.10)',
          color: '#1C1B1A',
          '&:hover': { backgroundColor: '#F4F3F0', borderColor: 'rgba(28,27,26,0.16)' },
        },
      },
    },
    MuiTextField: {
      defaultProps: { size: 'small', variant: 'outlined' },
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: '6px',
            backgroundColor: '#F1F0ED',
            fontSize: '14px',
            '& fieldset': { borderColor: 'rgba(28,27,26,0.10)' },
            '&:hover fieldset': { borderColor: 'rgba(28,27,26,0.16)' },
            '&.Mui-focused fieldset': {
              borderColor: '#C4913A',
              borderWidth: '1px',
              boxShadow: '0 0 0 3px rgba(196,145,58,0.25)',
            },
          },
          '& .MuiInputLabel-root': {
            fontSize: '13px',
            fontWeight: 500,
            color: '#1C1B1A',
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: '4px', height: '22px', fontSize: '12px', fontWeight: 600 },
        colorPrimary: { backgroundColor: '#FDF6EC', color: '#C4913A' },
        colorSuccess: { backgroundColor: '#EFF7F2', color: '#2D6944' },
        colorError: { backgroundColor: '#FDF0ED', color: '#A33820' },
        colorWarning: { backgroundColor: '#FEF9EC', color: '#8C6307' },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: '8px',
          border: '1px solid rgba(28,27,26,0.06)',
          boxShadow: '0 1px 3px rgba(28,27,26,0.06), 0 1px 2px rgba(28,27,26,0.04)',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: '12px',
          border: '1px solid rgba(28,27,26,0.06)',
          boxShadow: '0 20px 25px rgba(28,27,26,0.06), 0 8px 10px rgba(28,27,26,0.03)',
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 500,
          fontSize: '14px',
          minHeight: '36px',
          padding: '8px 16px',
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: { fontSize: '12px', borderRadius: '6px' },
      },
    },
    MuiAvatar: {
      styleOverrides: {
        root: {
          fontWeight: 600,
          fontSize: '13px',
        },
        colorDefault: {
          backgroundColor: '#F4F3F0',
          color: '#6B6966',
        },
      },
    },
  },
})

export default talosTheme
