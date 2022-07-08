% convervconvertUG_BIDS(sublist(s) + 100); % friend outsidet all trust
sublist = [104 105 106 107 108 109 110 111 112 113 115 116 ...
    117 118 120 121 122 124 125 126 127 128 129 130 131 132 133 134 135 136 137 138 140 141 142 ...
    143 144 145 147 149:159];

for s = 1:length(sublist)
    if sublist(s) == 143
        copyfile psychopy/logs/sub-143/func/*.tsv ../bids/sub-143/func/
        % don't redo since we had to remake ultimatum by hand
    else
        convertUG_BIDS(sublist(s)); % scanner outside
        convertUG_BIDS(sublist(s) + 100); % friend outside
    end
end
