import { useTranslation } from 'react-i18next';
import { Button } from './ui/button';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from './ui/dropdown-menu';
import { Languages } from 'lucide-react';

export const LanguageSwitcher = () => {
    const { i18n } = useTranslation();

    const languages = [
        { code: 'en', label: 'English', flag: 'EN' },
        { code: 'ru', label: 'Русский', flag: 'RU' },
    ];

    const currentLanguage = languages.find(l => l.code === i18n.language) || languages[1];

    const changeLanguage = (lng) => {
        i18n.changeLanguage(lng);
    };

    return (
        <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="outline"
                    size="sm"
                    className="gap-2 bg-white/40 text-foreground border border-white/30 shadow-sm hover:bg-white/50 transition-all font-medium"
                >
                    <Languages size={16} className="text-primary" />
                    <span>{currentLanguage.flag}</span>
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="bg-white/75 border border-white/40 shadow-md backdrop-blur-sm">
                {languages.map((lang) => (
                    <DropdownMenuItem
                        key={lang.code}
                        onClick={() => changeLanguage(lang.code)}
                        className={`cursor-pointer transition-colors ${i18n.language === lang.code
                                ? 'bg-primary/10 text-primary font-bold'
                                : 'hover:bg-primary/5'
                            }`}
                    >
                        <span className="flex items-center gap-2">
                            <span className="text-xs font-mono opacity-60">{lang.flag}</span>
                            {lang.label}
                        </span>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    );
};
