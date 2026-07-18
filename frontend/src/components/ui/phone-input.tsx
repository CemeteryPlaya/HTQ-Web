import React, { useCallback } from 'react';
import { Input } from '@/components/ui/input';

interface PhoneInputProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    className?: string;
    readOnly?: boolean;
}

/**
 * Masked phone input for Kazakhstan numbers.
 * Format: +7 (XXX) XXX-XX-XX
 * Auto-prefixes +7 and formats as user types.
 */
export const PhoneInput: React.FC<PhoneInputProps> = ({
    value,
    onChange,
    placeholder = '+7 (___) ___-__-__',
    className,
    readOnly,
}) => {
    const formatPhone = useCallback((raw: string): string => {
        // Strip everything except digits
        const digits = raw.replace(/\D/g, '');

        // Remove leading 8 or 7 (we always prefix +7)
        let clean = digits;
        if (clean.startsWith('7') || clean.startsWith('8')) {
            clean = clean.slice(1);
        }

        // Limit to 10 digits (after country code)
        clean = clean.slice(0, 10);

        // Build formatted string
        let result = '+7';
        if (clean.length > 0) {
            result += ' (' + clean.slice(0, 3);
        }
        if (clean.length >= 3) {
            result += ') ' + clean.slice(3, 6);
        }
        if (clean.length >= 6) {
            result += '-' + clean.slice(6, 8);
        }
        if (clean.length >= 8) {
            result += '-' + clean.slice(8, 10);
        }

        return result;
    }, []);

    const handleChange = useCallback(
        (e: React.ChangeEvent<HTMLInputElement>) => {
            const formatted = formatPhone(e.target.value);
            onChange(formatted);
        },
        [formatPhone, onChange]
    );

    const handleFocus = useCallback(() => {
        // If empty, pre-fill with +7
        if (!value) {
            onChange('+7');
        }
    }, [value, onChange]);

    return (
        <Input
            type="tel"
            value={value}
            onChange={handleChange}
            onFocus={handleFocus}
            placeholder={placeholder}
            className={className}
            readOnly={readOnly}
            maxLength={18}
        />
    );
};

export default PhoneInput;
