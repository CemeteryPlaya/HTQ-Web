import React, { useEffect, useState } from 'react';
import api from '../api/client';
import { apiPath } from '../api/endpoints';

function ItemsList() {
    const [items, setItems] = useState([]);
    const [error, setError] = useState('');

    const fetchItems = async () => {
        try {
            const res = await api.get(apiPath('users', 'items/'));
            setItems(res.data);
        } catch (err) {
            console.error(err);
            setError('Failed to fetch items');
        }
    };

    useEffect(() => {
        fetchItems();
    }, []);

    return (
        <div className="p-4 max-w-2xl mx-auto mt-4">
            <h2 className="text-xl mb-4">My Items</h2>
            {error && <p className="text-red-500 mb-2">{error}</p>}
            <ul className="space-y-2">
                {items.map(item => (
                    <li key={item.id} className="p-3 border rounded shadow-sm">
                        <h3 className="font-bold">{item.title}</h3>
                        <p className="text-gray-600">{item.description}</p>
                    </li>
                ))}
                {items.length === 0 && <p className="text-gray-500">No items found.</p>}
            </ul>
        </div>
    );
}

export default ItemsList;
