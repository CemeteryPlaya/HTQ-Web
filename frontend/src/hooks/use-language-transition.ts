import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

export const useLanguageTransition = () => {
  const { i18n } = useTranslation();
  const [isChanging, setIsChanging] = useState(false);

  useEffect(() => {
    setIsChanging(true);
    const timer = setTimeout(() => setIsChanging(false), 400);
    return () => clearTimeout(timer);
  }, [i18n.language]);

  return isChanging;
};
